import yaml
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from agent.context import DataAgentContext
from agent.llm import llm
from agent.state import DataAgentState
from app.core.log import logger
from app.prompt.prompt_loader import load_prompt


def _clean_sql(sql: str) -> str:
    sql = sql.strip()
    if sql.startswith("```"):
        lines = sql.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        sql = "\n".join(lines).strip()
    if not sql.lower().startswith("select") and "order_amount" in sql:
        sql = f"SELECT {sql} FROM fact_order"
    return sql

async def correct_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "校正SQL", "status": "running"})

    sql = state["sql"]
    error = state["error"]

    query = state["query"]
    table_infos = state["table_infos"]
    metric_infos = state["metric_infos"]
    date_info = state["date_info"]
    db_info = state["db_info"]

    try:
        prompt = PromptTemplate(
            template=load_prompt("correct_sql"),
            input_variables=["query", "table_infos", "metric_infos", "date_info", "db_info", "sql", "error"],
        )
        output_parser = StrOutputParser()

        chain = prompt | llm | output_parser

        result = await chain.ainvoke(
            {"query": query,
             "table_infos": yaml.dump(table_infos, allow_unicode=True, sort_keys=False),
             "metric_infos": yaml.dump(metric_infos, allow_unicode=True, sort_keys=False),
             "date_info": yaml.dump(date_info, allow_unicode=True, sort_keys=False),
             "db_info": yaml.dump(db_info, allow_unicode=True, sort_keys=False),
             "sql": sql,
             "error": error
             })
        result = _clean_sql(result)
        writer({"type": "progress", "step": "校正SQL", "status": "success"})
        logger.info(f"校正后的SQL: {result}")
        return {"sql": result}
    except Exception as e:
        writer({"type": "progress", "step": "校正SQL", "status": "error"})
        logger.error(f"校正SQL失败:{str(e)}")
        raise
