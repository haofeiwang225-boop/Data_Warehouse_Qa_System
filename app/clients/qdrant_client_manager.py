import asyncio
import random
from typing import Optional

from qdrant_client import AsyncQdrantClient, models

from app.conf.app_config import QdrantConfig, app_config


class QdrantClientManager:
    """
    Qdrant 向量数据库的客户端管理器。
    负责创建、初始化和关闭与 Qdrant 服务的异步连接。
    """

    def __init__(self, qdrant_config: QdrantConfig):
        """
        初始化管理器，保存配置，但此时还 不建立 连接。

        Args:
            qdrant_config: Qdrant 的连接配置（host、port 等）
        """
        self.qdrant_config = qdrant_config
        # client 初始为 None，等调用 init() 后才会真正连接
        self.client: Optional[AsyncQdrantClient] = None

    def _get_url(self):
        """
        根据配置拼接 Qdrant 的 HTTP 地址。
        例如: "http://localhost:6333"
        """
        return f"http://{self.qdrant_config.host}:{self.qdrant_config.port}"

    def init(self):
        """
        创建异步 Qdrant 客户端实例。
        调用后 self.client 才可用。
        """
        self.client = AsyncQdrantClient(url=self._get_url())

    async def close(self):
        """
        关闭与 Qdrant 的连接，释放资源。
        通常在应用退出时调用。
        """
        await self.client.close()


# ============================================================
# 模块级别的单例：整个应用共享同一个管理器实例
# 其他地方只需要 from app.clients.qdrant_client_manager import qdrant_client_manager
# ============================================================
qdrant_client_manager = QdrantClientManager(app_config.qdrant)

# ============================================================
# 以下为测试代码，直接运行此文件时执行
# 命令: python -m app.clients.qdrant_client_manager
# ============================================================
if __name__ == '__main__':
    # 第1步：初始化客户端，建立与 Qdrant 的连接
    qdrant_client_manager.init()

    async def test():
        client = qdrant_client_manager.client

        # ---- 第2步：如果集合不存在，就创建 ----
        if not await client.collection_exists("my_collection"):
            await client.create_collection(
                collection_name="my_collection",
                # vectors_config: 定义向量的参数
                #   size=10       → 每个向量是 10 维
                #   distance=COSINE → 用余弦相似度计算距离
                vectors_config=models.VectorParams(size=10, distance=models.Distance.COSINE),
            )

        # ---- 第3步：插入 100 条随机向量数据 ----
        await client.upsert(
            collection_name="my_collection",
            points=[
                models.PointStruct(
                    id=i,                                      # 向量的唯一 ID
                    vector=[random.random() for _ in range(10)],  # 10 维随机向量
                )
                for i in range(100)  # 生成 100 个点
            ],
        )

        # ---- 第4步：用一个随机向量做相似度搜索 ----
        res = await client.query_points(
            collection_name="my_collection",
            query=[random.random() for _ in range(10)],  # 查询向量（10 维随机）
            limit=10,              # 最多返回 10 条结果
            score_threshold=0.8    # 只返回相似度 >= 0.8 的结果
        )

        # ---- 第5步：打印搜索结果 ----
        print(res)

    # 运行异步测试函数
    asyncio.run(test())
