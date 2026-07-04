from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class DWMySQLRepository:
    """数仓 MySQL 仓库，负责执行 SQL、查询表结构和字段取值等操作。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_column_types(self, table_name: str) -> dict[str, str]:
        """获取指定表的所有字段名及其类型，返回 {字段名: 类型} 的字典。"""
        sql = f"show columns from {table_name}"
        result = await self.session.execute(text(sql))
        # fetchall() 返回所有行，每行是 Row 对象，通过 .Field 和 .Type 访问列值
        return {row.Field: row.Type for row in result.fetchall()}

    async def get_column_values(self, table_name: str, column_name: str, limit: int):
        """获取指定表某列的去重取值，用于构建筛选条件或枚举值提示。"""
        sql = f"select distinct {column_name} from {table_name} limit {limit}"
        result = await self.session.execute(text(sql))
        # scalars() 将结果转为单列模式，fetchall() 取出所有值，返回一维列表
        return [self._json_safe_value(value) for value in result.scalars().fetchall()]

    @staticmethod
    def _json_safe_value(value):
        if isinstance(value, Decimal):
            return float(value)
        return value

    async def get_db_info(self):
        """获取数据库版本和方言类型（如 mysql、postgresql），用于 SQL 方言适配。"""
        result = await self.session.execute(text("select version()"))
        version = result.scalar()

        dialect = self.session.get_bind().dialect.name

        return {'version': version, 'dialect': dialect}

    async def validate_sql(self, sql):
        """通过 EXPLAIN 验证 SQL 语法是否正确，语法错误会抛出异常。"""
        await self.session.execute(text(f"explain {sql}"))

    async def execute_sql(self, sql):
        """执行 SQL 查询，返回字典列表，每个字典代表一行结果。"""
        result = await self.session.execute(text(sql))
        # mappings().fetchall() 返回字典形式的行（列名 -> 值），再转为 dict 列表
        return [dict(row) for row in result.mappings().fetchall()] #mappings() 的作用就是把结果从元组模式转为字典模式
