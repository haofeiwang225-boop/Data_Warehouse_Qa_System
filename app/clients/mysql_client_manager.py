
# ============================================================
# 第一步：导入依赖
#   - DBConfig: 数据库配置的数据类（包含 host、port、user、password、database 等字段）
#   - app_config: 全局应用配置实例，从中读取数据库连接信息
# ============================================================
from app.conf.app_config import DBConfig, app_config


# ============================================================
# 第二步：定义 MySQL 客户端管理类
#   封装了 SQLAlchemy 异步引擎的生命周期管理（创建、获取URL、销毁）
# ============================================================
class MySQLClientmannagr:
    def __init__(self, config: DBConfig):
        # 第三步：初始化引擎为空，等待调用 init() 时再创建
        #   engine 是 SQLAlchemy 的核心对象，负责管理数据库连接池
        self.engine: AsynEngine | None = None # # 先占位，不连数据库
        self.config = config
        self.session_frctory = None


    def _get_url(self):
        # 第四步：根据配置拼接数据库连接字符串
        #   格式: mysql+asyncmy://用户名:密码@主机:端口/数据库名
        #   asyncmy 是异步 MySQL 驱动，配合 SQLAlchemy 异步引擎使用
        pass

    def init(self):
        # 第五步：创建异步引擎
        #   create_async_engine 内部会初始化一个连接池：
        #     - 建立一批数据库连接并保持活跃
        #     - 后续每次执行 SQL 时从池中借出连接，用完归还
        #     - 避免每次请求都重新握手认证
        self.engine = create_async_engine(self._get_url(), pool_pre_ping=True,pool_size=3)#
        # pool_pre_ping 借连接前先探测是否活着，避免拿到死连接
        # pool_size 连接池启动后会主动创建 3 个连接，一直保持打开状态，即使没有请求也不会关闭。
        #如果请求超过 3 个怎么办？ max_overflow（默认 10），允许临时多创建几个：

        self.session_frctory = async_sessionmaker(self.engine, autoflash=True, expire_on_commit=False)
#autoflash 执行查询前自动把未提交的改动刷到数据库（确保查询结果是最新的）
    #expire_on_commit  提交事务后不让对象属性过期，之后还能直接访问属性而不用重新查询
    async def close(self):
        await self.engine.dispose()


# ============================================================
# 第七步：创建两个全局单例
#   - meta_mysql_client_manager: 连接元数据库（存表结构、业务配置等）
#   - dw_mysql_client_manager:   连接数仓（存业务数据、分析结果等）
#   这两个实例在应用启动时由外部调用 init() 初始化引擎
# ============================================================
meta_mysql_client_manager = MySQLClientmannagr(app_config.db_meta)
dw_mysql_client_manager = MySQLClientmannagr(app_config.db_dw)

if __name__ == '__main__':
    dw_mysql_client_manager.init()
    engine = dw_mysql_client_manager.engine

    async def test():
        async with dw_mysql_client_manager.session_frctory() as session:
            sql = "select * from fact_order limit 10"
            result = await session.execute(text(sql))

            rows = result.fetchall()

            print(rows)
