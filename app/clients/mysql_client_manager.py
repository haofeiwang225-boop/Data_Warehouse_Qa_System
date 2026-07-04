from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.conf.app_config import DBConfig, app_config


class MySQLClientmannagr:
    def __init__(self, config: DBConfig):
        self.config = config
        self.engine: AsyncEngine | None = None
        self.session_factory = None

    def _get_url(self):
        return (
            f"mysql+asyncmy://{self.config.user}:{self.config.password}"
            f"@{self.config.host}:{self.config.port}/{self.config.database}"
            "?charset=utf8mb4"
        )

    def init(self):
        self.engine = create_async_engine(self._get_url(), pool_pre_ping=True, pool_size=3)
        self.session_factory = async_sessionmaker(
            self.engine,
            autoflush=True,
            expire_on_commit=False,
        )

    async def close(self):
        if self.engine is not None:
            await self.engine.dispose()


meta_mysql_client_manager = MySQLClientmannagr(app_config.db_meta)
dw_mysql_client_manager = MySQLClientmannagr(app_config.db_dw)


if __name__ == '__main__':
    dw_mysql_client_manager.init()

    async def test():
        async with dw_mysql_client_manager.session_factory() as session:
            result = await session.execute(text("select * from fact_order limit 10"))
            print(result.fetchall())
