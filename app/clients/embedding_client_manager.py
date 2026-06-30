from typing import Optional

import httpx

from app.conf.app_config import EmbeddingConfig, app_config


class EmbeddingClientManager:
    """本地 Text Embeddings Inference (TEI) 服务的客户端管理器"""

    def __init__(self, config: EmbeddingConfig):
        self.client: Optional[httpx.Client] = None
        self.config = config

    def _get_url(self):
        """拼接本地 TEI 服务的地址"""
        return f"http://{self.config.host}:{self.config.port}"

    def init(self):
        """初始化 HTTP 客户端"""
        self.client = httpx.Client(base_url=self._get_url())

    def embed_query(self, text: str) -> list[float]:
        """对单条文本进行向量化，返回 embedding 向量"""
        resp = self.client.post("/embed", json={"inputs": text})
        resp.raise_for_status()
        return resp.json()[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """对多条文本进行向量化，返回 embedding 向量列表"""
        resp = self.client.post("/embed", json={"inputs": texts})
        resp.raise_for_status()
        return resp.json()


embedding_client_manager = EmbeddingClientManager(app_config.embedding)


if __name__ == '__main__':
    embedding_client_manager.init()

    text = "wanghaofei"

    query_text = embedding_client_manager.embed_query(text)
    print(query_text[:3])