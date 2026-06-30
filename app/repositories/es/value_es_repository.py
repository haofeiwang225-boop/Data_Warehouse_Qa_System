"""
列枚举值的 Elasticsearch 仓库

职责：把列的具体取值（枚举值）存入 Elasticsearch，支持关键词全文搜索。

场景：用户问"状态为已完成的订单"，
     agent 通过 ES 搜索"已完成"，命中 status 列，
     就知道要把 WHERE status = '已完成' 拼进 SQL。

ES 中的数据结构：
  index（索引）→ 类似数据库的"表"
    └── document（文档）→ 每条文档包含：
          ├── id        → 唯一标识（格式：表名.列名.值，如 orders.status.已完成）
          ├── value     → 具体的值（如 "已完成"）
          └── column_id → 所属列的标识（如 "orders.status"）
"""

from dataclasses import asdict

from elasticsearch import AsyncElasticsearch

from app.entities.value_info import ValueInfo


class ValueESRepository:
    """
    列枚举值的 ES 仓库

    负责：
      1. 确保 ES 中有对应的 index
      2. 把枚举值批量写入 ES
    """

    # ES 索引名称，所有列的枚举值都存在这个索引里
    index_name = 'data-agent-value'

    # 索引的字段映射（schema），定义每个字段的类型和分词方式
    index_mappings = {
        "dynamic": False,  # 不自动添加未定义的字段，保持索引结构干净
        "properties": {
            # id 字段：keyword 类型，不分词，精确匹配
            # 适合做唯一标识，如 "orders.status.已完成"
            "id": {"type": "keyword"},

            # value 字段：text 类型，使用 ik 中文分词器
            # ik_max_word 会把中文尽量细粒度切分，如"已完成" → ["已完成", "完成"]
            # 这样搜"完成"也能命中"已完成"
            # analyzer: 写入时的分词器
            # search_analyzer: 搜索时的分词器，保持一致
            "value": {"type": "text", "analyzer": "ik_max_word", "search_analyzer": "ik_max_word"},

            # column_id 字段：keyword 类型，不分词，精确匹配
            # 适合做筛选条件，如"给我所有 orders.status 列的值"
            "column_id": {"type": "keyword"}
        }
    }

    def __init__(self, client: AsyncElasticsearch):
        """
        初始化，注入 ES 异步客户端

        Args:
            client: AsyncElasticsearch 实例，由 es_client_manager 提供
        """
        self.client = client

    async def ensure_index(self):
        """
        确保 index 存在，不存在则创建

        类似于 MySQL 的 CREATE TABLE IF NOT EXISTS。
        创建时会应用上面定义的 index_mappings（字段映射）。
        """
        if not await self.client.indices.exists(index=self.index_name):
            await self.client.indices.create(
                index=self.index_name,
                mappings=self.index_mappings,
            )

    async def index(self, value_infos: list[ValueInfo], batch_size=20):
        """
        批量写入枚举值到 ES

        ES 的 bulk API 格式要求每条数据前面跟一个 action 元数据：
          {"index": {"_index": "索引名", "_id": "文档ID"}}  ← 告诉 ES "我要写入"
          {"value": "已完成", "column_id": "orders.status"} ← 实际数据
          {"index": {"_index": "索引名", "_id": "文档ID"}}  ← 下一条
          {"value": "进行中", "column_id": "orders.status"} ← 实际数据
          ...

        所以 operations 列表是"元数据和数据交替排列"的。

        Args:
            value_infos: 要写入的枚举值列表
            batch_size:  每批写入多少条，默认 20
        """
        # 按 batch_size 分批处理
        for i in range(0, len(value_infos), batch_size):
            batch = value_infos[i:i + batch_size]

            # 构造 bulk API 的请求体
            operations = []
            for value_info in batch:
                # 元数据行：告诉 ES 这条文档写到哪个索引、用什么 ID
                operations.append({
                    "index": {
                        "_index": self.index_name,        # 目标索引
                        "_id": value_info.id,             # 文档 ID，如 "orders.status.已完成"
                    }
                })
                # 数据行：实际的文档内容
                # asdict() 把 ValueInfo dataclass 转成字典，ES 只接受字典格式
                operations.append(asdict(value_info))

            # 调用 ES 的 bulk 接口，一次性写入一批文档
            await self.client.bulk(operations=operations)

    async def search(self, keyword: str, score_threshold: float = 0.6, limit: int = 5) -> list[ValueInfo]:
        result = await self.client.search(index=self.index_name,
                                          query={
                                              "match": {
                                                  "value": keyword
                                              }
                                          },
                                          min_score=score_threshold,
                                          size=limit)
        return [ValueInfo(**hit['_source']) for hit in result['hits']['hits']]
