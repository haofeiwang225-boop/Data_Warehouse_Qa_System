"""
元知识库构建脚本

功能：从元数据MySQL、数据仓库MySQL中读取业务元数据，
     经过Embedding向量化后，写入Qdrant（向量数据库）和Elasticsearch（全文搜索），
     最终构建出可供AI Agent检索使用的元知识库。

使用方式：
    python -m app.scrips.build_meta_knowledge -c <配置文件路径>
"""

import asyncio
from argparse import ArgumentParser
from pathlib import Path

# ============================================================
# 第一步：导入所需的客户端管理器
# 这些管理器负责管理各个外部服务的连接生命周期（初始化、获取客户端、关闭）
# ============================================================
from app.clients.embedding_client_manager import embedding_client_manager  # Embedding模型客户端管理器
from app.clients.es_client_manager import es_client_manager  # Elasticsearch客户端管理器
from app.clients.mysql_client_manager import (
    meta_mysql_client_manager,  # 元数据MySQL客户端管理器
    dw_mysql_client_manager,    # 数据仓库MySQL客户端管理器
)
from app.clients.qdrant_client_manager import qdrant_client_manager  # Qdrant向量数据库客户端管理器

# ============================================================
# 第二步：导入数据访问层（Repository）
# 每个Repository封装了对特定存储的读写操作
# ============================================================
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository  # 列信息的Qdrant存储
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository  # 数据仓库MySQL存储
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository  # 元数据MySQL存储
from app.repositories.es.value_es_repository import ValueESRepository  # 值信息的ES存储
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository  # 指标的Qdrant存储

# ============================================================
# 第三步：导入业务服务层
# MetaKnowledgeService 负责编排整个元知识库的构建流程
# ============================================================
from app.services.meta_knowledge_service import MetaKnowledgeService


async def build(config_path: Path):
    """
    元知识库构建的主流程函数

    整体流程：
        1. 初始化所有外部服务的客户端连接
        2. 创建各Repository实例并注入到Service中
        3. 调用Service执行构建逻辑
        4. 关闭所有客户端连接，释放资源

    Args:
        config_path: 配置文件路径，包含数据库连接、Embedding模型等配置信息
    """

    # ----------------------------------------------------------
    # 阶段一：初始化所有客户端管理器
    # 每个init()会根据配置建立与对应服务的连接
    # ----------------------------------------------------------
    meta_mysql_client_manager.init()       # 连接元数据MySQL（存储表/列/指标的元信息）
    dw_mysql_client_manager.init()         # 连接数据仓库MySQL（存储实际业务数据）
    qdrant_client_manager.init()           # 连接Qdrant向量数据库（存储Embedding向量，用于语义检索）
    embedding_client_manager.init()        # 初始化Embedding客户端（将文本转换为向量）
    es_client_manager.init()               # 连接Elasticsearch（存储可枚举值，用于全文搜索）

    # ----------------------------------------------------------
    # 阶段二：创建Repository和Service实例
    # 使用async with管理MySQL会话，确保事务结束后自动释放连接
    # ----------------------------------------------------------

    #session 是 SQLAlchemy 的数据库会话，你可以把它理解为"一次数据库操作的上下文
    async with (
        meta_mysql_client_manager.session_factory() as meta_session,  # 获取元数据MySQL会话
        dw_mysql_client_manager.session_factory() as dw_session,      # 获取数据仓库MySQL会话
    ):
        # 2.1 创建数据访问层（Repository）实例
        meta_mysql_repository = MetaMySQLRepository(
            meta_session
        )  # 从元数据MySQL读取表、列、指标的定义信息

        dw_mysql_repository = DWMySQLRepository(
            dw_session
        )  # 从数据仓库MySQL读取实际数据（如枚举值等）

        column_qdrant_repository = ColumnQdrantRepository(
            qdrant_client_manager.client
        )  # 将列描述的Embedding向量写入Qdrant，支持语义相似度检索

        embedding_client = embedding_client_manager
        # Embedding客户端：调用模型将文本（如列名、描述）转换为向量表示

        value_es_repository = ValueESRepository(
            es_client_manager.client
        )  # 将枚举值/维度值写入Elasticsearch，支持关键词全文搜索

        metric_qdrant_repository = MetricQdrantRepository(
            qdrant_client_manager.client
        )  # 将指标描述的Embedding向量写入Qdrant，支持语义相似度检索

        # 2.2 创建业务服务层实例，注入所有依赖的Repository
        mete_knowledge_service = MetaKnowledgeService(
            meta_mysql_repository=meta_mysql_repository,        # 元数据源
            dw_mysql_repository=dw_mysql_repository,            # 数仓源
            column_qdrant_repository=column_qdrant_repository,  # 列向量存储
            embedding_client=embedding_client,                  # 向量化能力
            value_es_repository=value_es_repository,            # 值搜索存储
            metric_qdrant_repository=metric_qdrant_repository,  # 指标向量存储
        )

        # ----------------------------------------------------------
        # 阶段三：执行构建
        # Service内部会：
        #   1. 从MySQL读取所有元数据（表、列、指标定义）
        #   2. 对描述文本做Embedding向量化
        #   3. 将向量存入Qdrant，将可搜索的值存入ES
        # ----------------------------------------------------------
        await mete_knowledge_service.build(config_path)

    # ----------------------------------------------------------
    # 阶段四：关闭所有客户端连接，释放资源
    # Embedding客户端一般无需显式关闭，其余客户端需要
    # ----------------------------------------------------------
    await meta_mysql_client_manager.close()   # 关闭元数据MySQL连接
    await dw_mysql_client_manager.close()     # 关闭数据仓库MySQL连接
    await qdrant_client_manager.close()       # 关闭Qdrant连接
    await es_client_manager.close()           # 关闭Elasticsearch连接


if __name__ == "__main__":
    # ----------------------------------------------------------
    # 命令行入口：解析参数并启动构建流程
    # 示例：python -m app.scrips.build_meta_knowledge -c conf/conf.yaml
    # ----------------------------------------------------------
    parser = ArgumentParser(description="构建元知识库：从MySQL提取元数据，向量化后写入Qdrant和ES")

    parser.add_argument(
        "-c", "--conf",
        help="配置文件路径（YAML格式），包含数据库连接、Embedding模型等配置",
    )  # 接收 -c 或 --conf 参数指定配置文件路径

    args = parser.parse_args()

    config_path = Path(args.conf)  # 将字符串路径转为Path对象

    asyncio.run(build(config_path))  # 启动异步构建流程
