"""
元知识库构建服务

职责：读取 YAML 配置，把表、列、指标的元数据存入三个地方：
  1. meta MySQL —— 存结构化元数据（表定义、列定义、指标定义）
  2. Qdrant     —— 存向量（列描述、指标描述的 Embedding），用于语义检索
  3. ES         —— 存枚举值（列的具体取值），用于关键词搜索
"""

import uuid
from dataclasses import asdict
from pathlib import Path

from langchain_huggingface import HuggingFaceEndpointEmbeddings
from omegaconf import OmegaConf

from app.conf.meta_config import MetaConfig
from app.core.log import logger
from app.entities.column_info import ColumnInfo
from app.entities.column_metric import ColumnMetric
from app.entities.metric_info import MetricInfo
from app.entities.table_info import TableInfo
from app.entities.value_info import ValueInfo
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository


class MetaKnowledgeService:
    """
    元知识库构建服务

    通过构造函数注入所有外部依赖（Repository、Client），
    build() 是入口方法，按顺序调用各个私有方法完成构建。
    """

    def __init__(
        self,
        meta_mysql_repository: MetaMySQLRepository,    # meta 库的 Repository，负责存元数据
        dw_mysql_repository: DWMySQLRepository,        # 数仓的 Repository，负责查列类型和枚举值
        column_qdrant_repository: ColumnQdrantRepository,  # Qdrant 的列向量仓库
        embedding_client: HuggingFaceEndpointEmbeddings,   # Embedding 客户端，文本转向量
        value_es_repository: ValueESRepository,            # ES 的值仓库，存枚举值
        metric_qdrant_repository: MetricQdrantRepository,  # Qdrant 的指标向量仓库
    ):
        # 把外部依赖存到 self 上，后续方法中通过 self.xxx 访问
        self.meta_mysql_repository = meta_mysql_repository
        self.dw_mysql_repository = dw_mysql_repository
        self.column_qdrant_repository = column_qdrant_repository
        self.embedding_client = embedding_client
        self.value_es_repository = value_es_repository
        self.metric_qdrant_repository = metric_qdrant_repository

    async def _save_tables_to_meta_db(self, meta_config: MetaConfig) -> list[ColumnInfo]:
        """
        第2.1步：把表和列的元数据保存到 meta MySQL

        流程：
          1. 遍历配置中的每张表 → 构造 TableInfo 对象
          2. 对每张表的每一列：
             a) 从数仓查询该列的数据类型（如 varchar、int）
             b) 从数仓查询该列的 10 条示例值
             c) 构造 ColumnInfo 对象
          3. 批量保存到 meta 数据库

        Returns:
            所有列的 ColumnInfo 列表，后续步骤需要用到
        """
        table_infos: list[TableInfo] = []    # 存放所有表的信息
        column_infos: list[ColumnInfo] = []  # 存放所有列的信息

        for table in meta_config.tables:
            # 2.1.1 用配置中的表信息构造 TableInfo 对象
            table_info = TableInfo(
                id=table.name,          # 用表名作为 id
                name=table.name,        # 物理表名，如 "orders"
                role=table.role,        # 业务角色，如 "订单表"
                description=table.description,  # 表的详细描述
            )
            table_infos.append(table_info)

            # 2.1.2 从数仓查询这张表所有列的数据类型
            # 返回格式：{"order_id": "bigint", "amount": "decimal", ...}
            column_types: dict[str, str] = await self.dw_mysql_repository.get_column_types(table.name)

            for column in table.columns:
                # 2.1.3 从数仓查询该列的 10 条示例值
                # 比如 status 列可能返回 ["已完成", "进行中", "已取消"]
                column_values: list = await self.dw_mysql_repository.get_column_values(table.name, column.name, 10)

                # 2.1.4 构造 ColumnInfo 对象，把配置信息和查到的数据合并
                column_info = ColumnInfo(
                    id=f"{table.name}.{column.name}",  # 全局唯一标识，如 "orders.amount"
                    name=column.name,                   # 列名，如 "amount"
                    type=column_types[column.name],     # 数据类型，如 "decimal"
                    role=column.role,                   # 业务角色，如 "订单金额"
                    examples=column_values,             # 示例值列表
                    description=column.description,     # 列的详细描述
                    alias=column.alias,                 # 别名列表，如 ["金额", "总价"]
                    table_id=table.name,                # 所属表名
                )
                column_infos.append(column_info)

        # 2.1.5 把表和列的信息批量保存到 meta 数据库
        # session.begin() 开启事务，里面的所有操作要么全部成功，要么全部回滚
        async with self.meta_mysql_repository.session.begin():
            await self.meta_mysql_repository.save_table_infos(table_infos)
            await self.meta_mysql_repository.save_column_infos(column_infos)

        return column_infos  # 返回列信息，后面向量化和存 ES 都要用

    async def _save_column_info_to_qdrant(self, column_infos: list[ColumnInfo]):
        """
        第2.2步：把列的信息写入 Qdrant 向量数据库

        为每一列生成多个向量点：
          - 列名的向量
          - 列描述的向量
          - 每个别名的向量

        这样用户无论用"金额"还是"总价"还是"订单金额是多少"，
        都能通过语义相似度检索到 orders.amount 这一列。

        流程：
          1. 确保 Qdrant 的 collection 存在
          2. 为每列生成多个待向量化的文本（列名、描述、别名）
          3. 分批调用 Embedding 模型，把文本转成向量
          4. 批量写入 Qdrant
        """
        # 2.2.1 确保 Qdrant 中有对应的 collection（类似数据库的"表"）
        await self.column_qdrant_repository.ensure_collection()

        # 2.2.2 构造待保存的数据：每列生成多个点（列名、描述、每个别名各一个点）
        points: list[dict] = []
        for column_info in column_infos:
            # 点1：用列名作为检索文本
            points.append({
                "id": uuid.uuid4(),                        # 每个向量点的唯一 ID
                "embedding_text": column_info.name,        # 要向量化的文本 = 列名
                "payload": asdict(column_info),                    # 检索命中后返回的完整数据
            })
            # 点2：用列描述作为检索文本
            points.append({
                "id": uuid.uuid4(),
                "embedding_text": column_info.description, # 要向量化的文本 = 列描述
                "payload": column_info,
            })#Qdrant 里的 collection 就是存放向量的容器，类似于 MySQL 里的"表" collection = 向量的表，point = 向量的行。
            # 点3~N：用每个别名作为检索文本
            for alia in column_info.alias:
                points.append({
                    "id": uuid.uuid4(),
                    "embedding_text": alia,                # 要向量化的文本 = 别名
                    "payload": column_info,
                })

        # 2.2.3 提取所有待向量化的文本
        embedding_texts = [point["embedding_text"] for point in points]

        # 2.2.4 分批调用 Embedding 模型（每批 10 条），避免一次请求太多
        embedding_batch_size = 10
        embeddings = []
        for i in range(0, len(embedding_texts), embedding_batch_size):
            batch_embedding_texts = embedding_texts[i : i + embedding_batch_size]
            # aembed_documents 是异步批量向量化接口
            batch_embeddings = await self.embedding_client.aembed_documents(batch_embedding_texts)
            embeddings.extend(batch_embeddings)

        # 2.2.5 提取 id 和 payload 列表
        ids = [point["id"] for point in points]
        payloads = [point["payload"] for point in points]

        # 2.2.6 批量写入 Qdrant：id + 向量 + 附加数据
        await self.column_qdrant_repository.upsert(ids, embeddings, payloads)

    async def _save_value_info_to_es(
        self, meta_config: MetaConfig, column_infos: list[ColumnInfo]
    ):
        """
        第2.3步：把列的枚举值写入 Elasticsearch

        对于配置中标记了 sync=True 的列：
          1. 从数仓查询该列的所有不重复值（最多 10 万条）
          2. 构造 ValueInfo 对象
          3. 批量写入 ES

        目的：用户问"状态为已完成的订单"时，ES 能通过关键词匹配找到 status="已完成"
        """
        # 2.3.1 确保 ES 中有对应的 index（类似数据库的"表"）
        await self.value_es_repository.ensure_index()

        # 2.3.2 从配置中提取每列的 sync 标记
        # 格式：{"orders.status": True, "orders.amount": False, ...}
        column2sync: dict[str, bool] = {}
        for table in meta_config.tables:
            for column in table.columns:
                column2sync[f"{table.name}.{column.name}"] = column.sync

        # 2.3.3 遍历所有列，只处理 sync=True 的列
        value_infos: list[ValueInfo] = []
        for column_info in column_infos:
            sync = column2sync[column_info.id]
            if sync:
                # 从数仓查询该列的所有取值（最多 10 万条）
                table_name = column_info.table_id
                column_name = column_info.name
                values = await self.dw_mysql_repository.get_column_values(
                    table_name, column_name, 100000
                )
                # 为每个值构造 ValueInfo 对象
                current_value_infos = [
                    ValueInfo(
                        id=f"{column_info.id}.{value}",  # 全局唯一标识，如 "orders.status.已完成"
                        value=value,                      # 具体的值，如 "已完成"
                        column_id=column_info.id,         # 所属列的标识，如 "orders.status"
                    )
                    for value in values
                ]
                value_infos.extend(current_value_infos)

        # 2.3.4 批量写入 Elasticsearch
        await self.value_es_repository.index(value_infos)

    async def _save_metrics_to_meta_db(self, meta_config) -> list[MetricInfo]:
        """
        第3.1步：把指标的元数据保存到 meta MySQL

        流程：
          1. 遍历配置中的每个指标 → 构造 MetricInfo 对象
          2. 为每个指标的关联列 → 构造 ColumnMetric 关联关系
          3. 批量保存到 meta 数据库

        ColumnMetric 是一张关联表，记录"哪个指标关联了哪些列"，
        例如：指标"销售额"关联了 orders.amount 列。
        """
        metric_infos: list[MetricInfo] = []      # 存放所有指标信息
        column_metrics: list[ColumnMetric] = []  # 存放指标和列的关联关系

        for metric in meta_config.metrics:
            # 3.1.1 构造 MetricInfo 对象
            metric_info = MetricInfo(
                id=metric.name,                        # 用指标名作为 id
                name=metric.name,                      # 指标名，如 "销售额"
                description=metric.description,        # 指标描述
                relevant_columns=metric.relevant_columns,  # 关联的列，如 ["orders.amount"]
                alias=metric.alias,                    # 别名，如 ["GMV", "总销售额"]
            )
            metric_infos.append(metric_info)

            # 3.1.2 为每个关联列构造 ColumnMetric 关联记录
            for relevant_column in metric.relevant_columns:
                column_metric = ColumnMetric(
                    column_id=relevant_column,  # 列标识，如 "orders.amount"
                    metric_id=metric.name,      # 指标标识，如 "销售额"
                )
                column_metrics.append(column_metric)

        # 3.1.3 保存到 meta 数据库（事务内）
        async with self.meta_mysql_repository.session.begin():
            await self.meta_mysql_repository.save_metric_infos(metric_infos)
            await self.meta_mysql_repository.save_column_metrics(column_metrics)

        return metric_infos  # 返回指标信息，后面向量化要用

    async def _save_metric_info_to_qdrant(self, metric_infos: list[MetricInfo]):
        """
        第3.2步：把指标的信息写入 Qdrant 向量数据库

        和列的向量化逻辑一样，为每个指标生成多个向量点：
          - 指标名的向量
          - 指标描述的向量
          - 每个别名的向量

        这样用户问"总销售额"、"GMV"、"订单金额总和"都能检索到"销售额"指标。
        """
        # 3.2.1 确保 Qdrant 中有对应的 collection
        await self.metric_qdrant_repository.ensure_collection()

        # 3.2.2 为每个指标生成多个待向量化的文本
        points: list[dict] = []
        for metric_info in metric_infos:
            # 点1：用指标名作为检索文本
            points.append({
                "id": uuid.uuid4(),
                "embedding_text": metric_info.name,
                "payload": metric_info,
            })
            # 点2：用指标描述作为检索文本
            points.append({
                "id": uuid.uuid4(),
                "embedding_text": metric_info.description,
                "payload": metric_info,
            })
            # 点3~N：用每个别名作为检索文本
            for alia in metric_info.alias:
                points.append({
                    "id": uuid.uuid4(),
                    "embedding_text": alia,
                    "payload": metric_info,
                })

        # 3.2.3 分批调用 Embedding 模型
        ids = [point["id"] for point in points]
        embeddings = []
        embedding_texts = [point["embedding_text"] for point in points]
        embedding_batch_size = 10
        for i in range(0, len(embedding_texts), embedding_batch_size):
            batch_embedding_texts = embedding_texts[i : i + embedding_batch_size]
            batch_embeddings = await self.embedding_client.aembed_documents(batch_embedding_texts)
            embeddings.extend(batch_embeddings)
        payloads = [point["payload"] for point in points]

        # 3.2.4 批量写入 Qdrant
        await self.metric_qdrant_repository.upsert(ids, embeddings, payloads)

    async def build(self, config_path: Path):
        """
        元知识库构建的入口方法

        整体流程：
          第1步：加载 YAML 配置文件
          第2步：处理表和列（保存元数据 → 向量化 → 存枚举值）
          第3步：处理指标（保存元数据 → 向量化）

        Args:
            config_path: YAML 配置文件路径
        """

        # ==============================================================
        # 第1步：加载并解析 YAML 配置文件
        #
        #   OmegaConf.load()           → 读 YAML 文件，变成字典
        #   OmegaConf.structured()     → 根据 MetaConfig dataclass 生成类型模板
        #   OmegaConf.merge()          → 合并字典和模板，补默认值 + 类型校验
        #   OmegaConf.to_object()      → 转成 Python dataclass 实例
        # ==============================================================
        context = OmegaConf.load(config_path)
        schema = OmegaConf.structured(MetaConfig)
        meta_config: MetaConfig = OmegaConf.to_object(OmegaConf.merge(schema, context))
        logger.info("加载配置文件")

        async with self.meta_mysql_repository.session.begin():
            await self.meta_mysql_repository.clear_all()

        # ==============================================================
        # 第2步：处理表和列
        # ==============================================================
        if meta_config.tables:
            # 2.1 保存表和列的元数据到 meta 数据库
            #     同时从数仓查出列的数据类型和示例值
            #     返回 ColumnInfo 列表，供后续步骤使用
            column_infos = await self._save_tables_to_meta_db(meta_config)
            logger.info("保存表信息到meta数据库")

            # 2.2 对列名、描述、别名做 Embedding 向量化，存入 Qdrant
            #     目的：用户提问时通过语义相似度找到最相关的列
            await self._save_column_info_to_qdrant(column_infos)
            logger.info("为字段信息建立向量索引")

            # 2.3 从数仓查出 sync=True 的列的所有枚举值，存入 ES
            #     目的：用户提问涉及具体值时通过关键词匹配找到
            await self._save_value_info_to_es(meta_config, column_infos)
            logger.info("为字段取值建立全文索引")

        # ==============================================================
        # 第3步：处理指标
         # ==============================================================
        if meta_config.metrics:
            # 3.1 保存指标元数据和指标-列关联关系到 meta 数据库
            metric_infos = await self._save_metrics_to_meta_db(meta_config)
            logger.info("保存指标信息到meta数据库")

            # 3.2 对指标名、描述、别名做 Embedding 向量化，存入 Qdrant
            #     目的：用户提问时通过语义相似度找到最相关的指标
            await self._save_metric_info_to_qdrant(metric_infos)
            logger.info("为指标信息建立向量索引")

        logger.info("元数据知识库构建完成")
 
