from dataclasses import asdict, is_dataclass

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct

from app.conf.app_config import app_config
from app.entities.metric_info import MetricInfo

class MetricQdrantRepository:
    collection_name: str = 'data-agent-metric'

    def __init__(self, client: AsyncQdrantClient):
        self.client = client

    async def ensure_collection(self):
        if not await self.client.collection_exists(self.collection_name):
            await self.client.create_collection(self.collection_name,
                                                vectors_config=VectorParams(size=app_config.qdrant.embedding_size,
                                                                            distance=Distance.COSINE))

    async def upsert(self, ids: list[str], embeddings: list[list[float]], payloads: list[MetricInfo],
                     batch_size: int = 20):
        zipped = list(zip(ids, embeddings, payloads))
        for i in range(0, len(zipped), batch_size):
            batch = zipped[i:i + batch_size]
            batch_points = [PointStruct(id=id, vector=embedding, payload=asdict(payload) if is_dataclass(payload) else payload) for id, embedding, payload in
                            batch]
            await self.client.upsert(collection_name=self.collection_name, points=batch_points)

    async def search(self, embedding: list[float], score_threshold: float = 0.6, limit: int = 5) -> list[MetricInfo]:
        result = await self.client.query_points(collection_name=self.collection_name, #相当于表名
                                                query=embedding,
                                                score_threshold=score_threshold,
                                                limit=limit)
        return [MetricInfo(**point.payload) for point in result.points]
    #result.points 是匹配到的点列表，每个点有 .payload（存入时附带的元数据，比如指标名、描述等）。
    # 用 MetricInfo(**point.payload) 把字典还原成 MetricInfo 对象返回。
