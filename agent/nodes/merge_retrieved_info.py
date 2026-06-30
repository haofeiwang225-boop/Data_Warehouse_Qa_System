from langgraph.runtime import Runtime

from agent.context import DataAgentContext
from agent.state import DataAgentState, TableInfoState, MetricInfoState, ColumnInfoState
from app.core.log import logger
from app.entities.column_info import ColumnInfo
from app.entities.table_info import TableInfo


async def merge_retrieved_info(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """
    合并召回信息节点

    作用：将前面三个召回节点的结果（字段、取值、指标）合并整理成结构化的表信息和指标信息，
         作为生成 SQL 的上下文传给 generate_sql 节点。

    为什么需要合并？
        前面召回的是零散的信息片段：
        - recall_column 召回了若干字段（如 order_amount、region_name）
        - recall_value 召回了若干取值（如 "华东" 对应 region_name）
        - recall_metric 召回了若干指标（如 GMV，关联字段 fact_order.order_amount）

        但 generate_sql 需要的是"完整的表结构"——知道哪些表、每个表有哪些字段、字段之间怎么关联。
        所以这个节点要把零散信息拼成结构化的 table_infos 和 metric_infos。

    处理流程（举例）：
        假设召回了：
        - 字段: [order_amount(table=fact_order), region_name(table=dim_region)]
        - 取值: [华东(column=region_name)]
        - 指标: [GMV(关联字段=fact_order.order_amount)]

        第一步：把指标关联的字段也加进来（order_amount 已存在，不重复加）
        第二步：把取值"华东"挂到 region_name 字段的 examples 里
        第三步：按 table_id 分组 → {fact_order: [order_amount], dim_region: [region_name]}
        第四步：给每个表补上主外键（如 fact_order 补上 order_id、customer_id 等）
        第五步：转成 TableInfoState 列表，附带表名、角色、描述、字段列表
    """

    writer = runtime.stream_writer
    writer({"type": "progress", "step": "合并召回信息", "status": "running"})

    # 从 state 中取出三个召回节点的结果
    retrieved_columns = state["retrieved_columns"]   # recall_column 的输出
    retrieved_values = state["retrieved_values"]      # recall_value 的输出
    retrieved_metrics = state["retrieved_metrics"]    # recall_metric 的输出

    # 从 runtime context 获取元数据仓库，用于补充缺失的字段/表信息
    meta_mysql_repository = runtime.context["meta_mysql_repository"]

    # 用 dict 存储所有字段，key 是字段 id，方便后续去重和查找
    # 例如: {"col_001": ColumnInfo(name="order_amount", ...), "col_002": ColumnInfo(name="region_name", ...)}
    retrieved_columns_map: dict[str, ColumnInfo] = {retrieved_column.id: retrieved_column for retrieved_column
                                                    in retrieved_columns}

    # 最终输出：表信息列表
    table_infos: list[TableInfoState] = []

    try:
        # ---- 第一步：把指标关联的字段补充到字段列表 ----
        # 例：指标 GMV 的 relevant_columns = ["fact_order.order_amount"]
        # 如果 order_amount 还没在召回结果里，就从 MySQL 元数据表查出来补上
        for retrieved_metric in retrieved_metrics:
            relevant_columns = retrieved_metric.relevant_columns
            for relevant_column in relevant_columns:
                if relevant_column not in retrieved_columns_map:
                    column_info = await meta_mysql_repository.get_column_info_by_id(relevant_column)
                    retrieved_columns_map[relevant_column] = column_info

        # ---- 第二步：把字段取值合并到对应字段的 examples 里 ----
        # 例：召回了 ValueInfo(value="华东", column_id="col_002"(region_name))
        #     → 把 "华东" 加到 region_name 字段的 examples 列表里
        #     这样 generate_sql 就知道 region_name 有哪些取值，生成 WHERE 条件时更准确
        for retrieved_value in retrieved_values:
            column_id = retrieved_value.column_id
            column_value = retrieved_value.value
            # 如果该字段还没在列表里，先从 MySQL 查出来
            if column_id not in retrieved_columns_map:
                column_info = await meta_mysql_repository.get_column_info_by_id(column_id)
                retrieved_columns_map[column_id] = column_info
            # 把取值加到字段的 examples 中（去重）
            if column_value not in retrieved_columns_map[column_id].examples:
                retrieved_columns_map[column_id].examples.append(column_value)

        # ---- 第三步：按 table_id 分组 ----
        # 例：所有字段按所属表分组：
        # {
        #   "fact_order": [ColumnInfo(name="order_amount", ...)],
        #   "dim_region": [ColumnInfo(name="region_name", ...)]
        # }
        table_to_columns_map: dict[str, list[ColumnInfo]] = {}
        for column in retrieved_columns_map.values():
            table_id = column.table_id
            if table_id not in table_to_columns_map:
                table_to_columns_map[table_id] = []
            table_to_columns_map[table_id].append(column)

        # ---- 第四步：给每个表补上主外键 ----
        # 例：fact_order 表当前只有 order_amount（度量），但生成 SQL 时需要 JOIN
        #     所以要补上主键 order_id 和外键 customer_id、product_id 等
        for table_id in table_to_columns_map.keys():
            # 从 MySQL 查询该表的所有主外键字段
            key_columns: list[ColumnInfo] = await meta_mysql_repository.get_key_columns_by_table_id(table_id)

            # 当前表已有的字段 id 列表，避免重复添加
            column_ids = [column.id for column in table_to_columns_map[table_id]]

            for key_column in key_columns:
                if key_column.id not in column_ids:
                    table_to_columns_map[table_id].append(key_column)

        # ---- 第五步：转成 TableInfoState 列表 ----
        # 把 table_id -> columns 的映射转成结构化的 TableInfoState
        # 例：TableInfoState(
        #         name="fact_order",
        #         role="fact",
        #         description="订单事实表",
        #         columns=[ColumnInfoState(name="order_amount", ...), ColumnInfoState(name="order_id", ...)]
        #     )
        for table_id, columns in table_to_columns_map.items():
            # 从 MySQL 查询表的元信息（表名、角色、描述）
            table: TableInfo = await meta_mysql_repository.get_table_info_by_id(table_id)
            # 将 ColumnInfo 实体转为 state 中使用的 ColumnInfoState（去掉 id、table_id 等内部字段）
            columns = [
                ColumnInfoState(name=column.name, type=column.type, role=column.role, examples=column.examples,
                                description=column.description, alias=column.alias)
                for column in columns]
            table_info_state = TableInfoState(name=table.name,
                                              role=table.role,
                                              description=table.description,
                                              columns=columns)
            table_infos.append(table_info_state)

        # 处理指标信息：将 MetricInfo 实体转为 state 中使用的 MetricInfoState
        metric_infos: list[MetricInfoState] = [
            MetricInfoState(name=metric_info.name, description=metric_info.description,
                            relevant_columns=metric_info.relevant_columns, alias=metric_info.alias)
            for metric_info in retrieved_metrics]

        writer({"type": "progress", "step": "合并召回信息", "status": "success"})
        logger.info(
            f"合并召回信息: 表信息-{[table_info['name'] for table_info in table_infos]},指标信息-{[metric_info['name'] for metric_info in metric_infos]}")

        # 将结构化的表信息和指标信息写入 state，供下游 filter_table、filter_metric、generate_sql 使用
        return {"table_infos": table_infos, "metric_infos": metric_infos}
    except Exception as e:
        writer({"type": "progress", "step": "合并召回信息", "status": "error"})
        logger.error(f"合并召回信息失败: {str(e)}")
        raise
