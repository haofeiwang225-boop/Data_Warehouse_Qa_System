"""
元知识库配置数据模型

定义了元知识库构建所需的配置结构，用于描述：
- 数据仓库中有哪些表、哪些列（TableConfig / ColumnConfig）
- 有哪些业务指标（MetricConfig）
- 整体配置的顶层结构（MetaConfig）

这些配置通常从 YAML 文件加载，供 MetaKnowledgeService 读取后执行构建。
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ColumnConfig:
    """
    列（字段）配置

    描述一张表中某一列的元信息，包括它的业务含义、别名等。
    示例：用户表中的 "user_name" 列，角色是"用户名"，别名可能有 ["姓名", "用户名称"]。
    """
    name: str          # 列的物理名称，对应数据库中的字段名，如 "user_name"
    role: str          # 列的业务角色，用简短的词描述这列是什么，如 "用户名"
    description: str   # 列的详细描述，解释这列存储什么数据、有什么业务含义
    alias: list[str]   # 列的别名列表，用户可能用不同的叫法来指代这一列，如 ["姓名", "用户昵称"]
    sync: bool         # 是否需要同步到知识库。False 表示跳过此列，不参与向量化和检索


@dataclass
class TableConfig:
    """
    表配置

    描述数据仓库中一张表的元信息，包含表的基本信息和下属的所有列配置。
    示例：一张 "orders" 订单表，包含 order_id、user_id、amount 等列。
    """
    name: str                  # 表的物理名称，对应数据库中的表名，如 "orders"
    role: str                  # 表的业务角色，简短描述这张表是什么，如 "订单表"
    description: str           # 表的详细描述，解释这张表存储什么数据、在业务中起什么作用
    columns: list[ColumnConfig]  # 该表包含的所有列配置


@dataclass
class MetricConfig:
    """
    业务指标配置

    描述一个可计算的业务指标，如"销售额"、"订单量"、"用户留存率"等。
    指标不直接对应某张表，而是通过 relevant_columns 关联到相关的列。
    示例：指标"销售额"关联到订单表的 "amount" 列。
    """
    name: str              # 指标名称，如 "销售额"
    description: str       # 指标的详细描述，解释这个指标怎么计算、代表什么业务含义
    relevant_columns: list[str]  # 与该指标相关的列名列表，格式为 "表名.列名"，如 ["orders.amount"]
    alias: list[str]       # 指标的别名列表，如 ["总销售额", "销售金额", "GMV"]


@dataclass
class MetaConfig:
    """
    元知识库顶层配置

    作为整个配置的根节点，包含所有表配置和指标配置。
    两个字段都是可选的，因为构建时可能只需要处理表或只需要处理指标。
    """
    tables: Optional[list[TableConfig]] = None    # 所有表的配置列表，None 表示不配置表
    metrics: Optional[list[MetricConfig]] = None  # 所有指标的配置列表，None 表示不配置指标
