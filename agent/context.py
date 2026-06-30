from typing import TypedDict

from langchain_huggingface import HuggingFaceEndpointEmbeddings

from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository


class DataAgentContext(TypedDict):
    """
    DataAgent 的运行时上下文，定义了所有节点需要用到的外部依赖。

    这些依赖在编译 graph 时注入，节点通过 runtime.context["xxx"] 获取，
    避免在每个节点内部自己创建连接，实现依赖解耦。

    包含三类服务：
        - 向量检索：embedding_client + qdrant 仓库（字段/指标的语义召回）
        - 全文检索：es 仓库（字段取值的关键词搜索）
        - 数据库访问：meta MySQL（元数据查询）+ dw MySQL（数仓 SQL 执行）
    """

    # Embedding 模型客户端，将文本转为 1024 维向量（bge-large-zh-v1.5）
    embedding_client: HuggingFaceEndpointEmbeddings

    # Qdrant 向量仓库：存储/检索字段描述的向量
    column_qdrant_repository: ColumnQdrantRepository

    # ES 仓库：存储/检索字段取值（如省份名称、商品类别等枚举值）
    value_es_repository: ValueESRepository

    # Qdrant 向量仓库：存储/检索指标描述的向量
    metric_qdrant_repository: MetricQdrantRepository

    # Meta MySQL 仓库：查询元数据（表结构、字段信息、主外键关系等）
    meta_mysql_repository: MetaMySQLRepository

    # DW MySQL 仓库：执行数仓 SQL、验证 SQL 语法、获取数据库环境信息
    dw_mysql_repository: DWMySQLRepository
