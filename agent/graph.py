import asyncio

from langgraph.constants import START, END
from langgraph.graph._branch import BranchSpec
from langgraph.graph import StateGraph
from langgraph.pregel._write import ChannelWrite

from agent.context import DataAgentContext
from agent.nodes.add_extra_context import add_extra_context
from agent.nodes.correct_sql import correct_sql
from agent.nodes.execute_sql import execute_sql
from agent.nodes.extract_keywords import extract_keywords
from agent.nodes.filter_metric import filter_metric
from agent.nodes.filter_table import filter_table
from agent.nodes.generate_sql import generate_sql
from agent.nodes.merge_retrieved_info import merge_retrieved_info
from agent.nodes.recall_column import recall_column
from agent.nodes.recall_metric import recall_metric
from agent.nodes.recall_value import recall_value
from agent.nodes.validate_sql import validate_sql
from agent.state import DataAgentState
from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import meta_mysql_client_manager, dw_mysql_client_manager
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository


_original_channel_awrite = ChannelWrite._awrite
_original_channel_write = ChannelWrite._write
_original_branch_aroute = BranchSpec._aroute
_original_branch_route = BranchSpec._route


async def _channel_awrite_compat(self, input, conf):
    return await _original_channel_awrite(self, input, conf)


def _channel_write_compat(self, input, conf):
    return _original_channel_write(self, input, conf)


async def _branch_aroute_compat(self, input, conf, *, reader, writer):
    return await _original_branch_aroute(self, input, conf, reader=reader, writer=writer)


def _branch_route_compat(self, input, conf, *, reader, writer):
    return _original_branch_route(self, input, conf, reader=reader, writer=writer)


ChannelWrite._awrite = _channel_awrite_compat
ChannelWrite._write = _channel_write_compat
BranchSpec._aroute = _branch_aroute_compat
BranchSpec._route = _branch_route_compat

graph_builder = StateGraph(state_schema=DataAgentState, context_schema=DataAgentContext)

# 添加节点
graph_builder.add_node("extract_keywords", extract_keywords)
graph_builder.add_node("recall_column", recall_column)
graph_builder.add_node("recall_value", recall_value)
graph_builder.add_node("recall_metric", recall_metric)
graph_builder.add_node("merge_retrieved_info", merge_retrieved_info)
graph_builder.add_node("filter_metric", filter_metric)
graph_builder.add_node("filter_table", filter_table)
graph_builder.add_node("add_extra_context", add_extra_context)
graph_builder.add_node("generate_sql", generate_sql)
graph_builder.add_node("validate_sql", validate_sql)
graph_builder.add_node("correct_sql", correct_sql)
graph_builder.add_node("execute_sql", execute_sql)

# 添加关系
graph_builder.add_edge(START, "extract_keywords")
graph_builder.add_edge("extract_keywords", "recall_column")
graph_builder.add_edge("extract_keywords", "recall_value")
graph_builder.add_edge("extract_keywords", "recall_metric")
graph_builder.add_edge("recall_column", "merge_retrieved_info")
graph_builder.add_edge("recall_value", "merge_retrieved_info")
graph_builder.add_edge("recall_metric", "merge_retrieved_info")
graph_builder.add_edge("merge_retrieved_info", "filter_table")
graph_builder.add_edge("merge_retrieved_info", "filter_metric")
graph_builder.add_edge("filter_table", "add_extra_context")
graph_builder.add_edge("filter_metric", "add_extra_context")
graph_builder.add_edge("add_extra_context", "generate_sql")
graph_builder.add_edge("generate_sql", "validate_sql")

graph_builder.add_conditional_edges("validate_sql",
                                    lambda state: "execute_sql" if state["error"] is None else "correct_sql",
                                    {"execute_sql": "execute_sql", "correct_sql": "correct_sql"})

graph_builder.add_edge("correct_sql", "execute_sql")
graph_builder.add_edge("execute_sql", END)

graph = graph_builder.compile()


if __name__ == '__main__':
    print(graph.get_graph().draw_ascii())
