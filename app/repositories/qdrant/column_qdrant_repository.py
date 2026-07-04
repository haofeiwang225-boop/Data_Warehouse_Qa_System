"""
列信息的 Qdrant 向量仓库

职责：把列的 Embedding 向量存入 Qdrant，支持语义相似度检索。
后续用户提问时，把问题也转成向量，在 Qdrant 中找最相似的列。

Qdrant 中的数据结构：
  collection（集合）→ 类似数据库的"表"
    └── point（向量点）→ 每个点包含：
          ├── id       → 唯一标识
          ├── vector   → Embedding 向量（1024 维浮点数组）
          └── payload  → 附加数据（完整的 ColumnInfo，检索命中后返回给调用方）
"""

from dataclasses import asdict, is_dataclass

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct

from app.conf.app_config import app_config
from app.entities.column_info import ColumnInfo


class ColumnQdrantRepository:
    """
    列信息的 Qdrant 向量仓库

    负责：
      1. 确保 Qdrant 中有对应的 collection
      2. 把列的向量批量写入 Qdrant
    """

    # Qdrant 中的集合名称，所有列的向量都存在这个集合里
    collection_name: str = 'data-agent-column'

    def __init__(self, client: AsyncQdrantClient):
        """
        初始化，注入 Qdrant 异步客户端

        Args:
            client: AsyncQdrantClient 实例，由 qdrant_client_manager 提供
        """
        self.client = client

    async def ensure_collection(self):
        """
        确保 collection 存在，不存在则创建
Qdrant 里的 collection 就是存放向量的容器，类似于 MySQL 里的"表" collection = 向量的表，point = 向量的行。
        类似于 MySQL 的 CREATE TABLE IF NOT EXISTS。
        创建时指定：
          - embedding_size: 向量维度（1024，由 bge-large-zh-v1.5 模型决定）
          - distance: 相似度算法（COSINE 余弦相似度，适合文本语义匹配）
        """
        if not await self.client.collection_exists(self.collection_name):
            await self.client.create_collection(
                self.collection_name,
                vectors_config=VectorParams(
                    size=app_config.qdrant.embedding_size,  # 向量维度 = 1024
                    distance=Distance.COSINE,                # 用余弦相似度计算距离
                ),
            )

    async def upsert(
        self,
        ids: list[str],                  # 每个向量点的唯一 ID
        embeddings: list[list[float]],   # 每个点的向量（1024 维浮点数组）
        payloads: list[ColumnInfo],      # 每个点的附加数据（完整的列信息）
        batch_size: int = 20,            # 每批写入的点数，默认 20
    ):
        """
        批量写入（upsert = update or insert）向量点到 Qdrant

        流程：
          1. 把 ids、embeddings、payloads 三个列表按位置一一配对
          2. 按 batch_size 分批
          3. 每批构造 PointStruct 列表，调用 Qdrant 的 upsert 接口写入

        为什么要分批？
          - 一次写入太多数据，Qdrant 请求体可能超大
          - 分批写入可以控制内存占用和网络传输大小

        Args:
            ids:        ID 列表，如 [uuid1, uuid2, uuid3, ...]
            embeddings: 向量列表，如 [[0.1, 0.2, ...], [0.3, 0.4, ...], ...]
            payloads:   附加数据列表，如 [ColumnInfo(...), ColumnInfo(...), ...]
            batch_size: 每批写入多少个点，默认 20
        """
        # 第1步：把三个列表按位置配对
        # zip([a,b,c], [1,2,3], [x,y,z]) → [(a,1,x), (b,2,y), (c,3,z)]
        zipped = list(zip(ids, embeddings, payloads))

        # 第2步：按 batch_size 分批处理
        for i in range(0, len(zipped), batch_size):
            batch = zipped[i:i + batch_size]

            # 第3步：把每条数据包装成 Qdrant 的 PointStruct
            # PointStruct 需要三个字段：id、vector、payload
            # asdict(payload) 把 ColumnInfo dataclass 转成字典，Qdrant 只接受字典格式
            batch_points = [
                PointStruct(
                    id=id,                          # 向量点的唯一标识
                    vector=embedding,               # 1024 维的 Embedding 向量
                    payload=asdict(payload) if is_dataclass(payload) else payload,
                )
                for id, embedding, payload in batch
            ]

            # 第4步：写入 Qdrant
            # upsert = update or insert，如果 id 已存在则覆盖，不存在则新增
            await self.client.upsert(
                collection_name=self.collection_name,
                points=batch_points,
            )

    async def search(self, embedding: list[float], score_threshold: float = 0.6, limit: int = 5) -> list[ColumnInfo]:
        result = await self.client.query_points(collection_name=self.collection_name,
                                                query=embedding,
                                                score_threshold=score_threshold,
                                                limit=limit)
        return [ColumnInfo(**point.payload) for point in result.points]
