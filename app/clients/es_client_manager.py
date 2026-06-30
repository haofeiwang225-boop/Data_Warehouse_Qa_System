import asyncio
from typing import Optional

from elasticsearch import AsyncElasticsearch

from app.conf.app_config import ESConfig, app_config


class ESClientManager:
    """Elasticsearch 异步客户端管理器，负责创建、管理和关闭 ES 连接"""

    def __init__(self, es_config: ESConfig):
        # 保存 ES 配置（host、port 等）
        self.es_config = es_config
        # 异步 ES 客户端实例，初始为 None，需调用 init() 初始化
        self.client: Optional[AsyncElasticsearch] = None

    def _get_url(self):
        """根据配置拼接 ES 的 HTTP 连接地址"""
        return f"http://{self.es_config.host}:{self.es_config.port}"

    def init(self):
        """初始化 ES 客户端，创建异步连接实例"""
        self.client = AsyncElasticsearch(hosts=[self._get_url()])

    async def close(self):
        """异步关闭 ES 客户端连接"""
        await self.client.close()


# 模块级单例，全局共享同一个 ES 客户端管理器实例
es_client_manager = ESClientManager(app_config.es)

if __name__ == '__main__':
    # 初始化 ES 客户端连接
    es_client_manager.init()

    async def test():
        client = es_client_manager.client

        # ========== 1. 创建索引 ==========
        # 定义 my-books 索引的字段映射（dynamic=False 表示不自动添加未定义的字段）
        await client.indices.create(
            index="my-books",
            mappings={
                "dynamic": False, #表示不自动添加未定义的字段）
                "properties": {
                    "name": {
                        "type": "text"
                    },
                    "author": {
                        "type": "text"
                    },
                    "release_date": {
                        "type": "date",
                        "format": "yyyy-MM-dd"
                    },
                    "page_count": {
                        "type": "integer"
                    }
                }
            },
        )

        # ========== 2. 批量插入数据 ==========
        # 使用 bulk API 一次性插入多条文档，每条数据前需跟一个 action 元数据（指定索引名）
        await client.bulk(
            operations=[
                {
                    "index": {
                        "_index": "my-books"
                    }
                },
                {
                    "name": "Revelation Space",
                    "author": "Alastair Reynolds",
                    "release_date": "2000-03-15",
                    "page_count": 585
                },
                {
                    "index": {
                        "_index": "my-books"
                    }
                },
                {
                    "name": "1984",
                    "author": "George Orwell",
                    "release_date": "1985-06-01",
                    "page_count": 328
                },
                {
                    "index": {
                        "_index": "my-books"
                    }
                },
                {
                    "name": "Fahrenheit 451",
                    "author": "Ray Bradbury",
                    "release_date": "1953-10-15",
                    "page_count": 227
                },
                {
                    "index": {
                        "_index": "my-books"
                    }
                },
                {
                    "name": "Brave New World",
                    "author": "Aldous Huxley",
                    "release_date": "1932-06-01",
                    "page_count": 268
                },
                {
                    "index": {
                        "_index": "my-books"
                    }
                },
                {
                    "name": "The Handmaids Tale",
                    "author": "Margaret Atwood",
                    "release_date": "1985-06-01",
                    "page_count": 311
                }
            ],
        )

        # ========== 3. 全文搜索 ==========
        # 在 my-books 索引中，对 name 字段执行 match 查询，搜索包含 "brave" 的文档
        resp = await client.search(
            index="my-books",
            query={
                "match": {
                    "name": "brave"
                }
            },
        )
        # 打印搜索结果
        print(resp)
        # 关闭 ES 连接
        await es_client_manager.close()

# 启动异步事件循环，运行测试函数
asyncio.run(test())
