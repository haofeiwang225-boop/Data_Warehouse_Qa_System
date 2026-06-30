from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from agent.context import DataAgentContext
from agent.llm import llm
from agent.state import DataAgentState
from app.core.log import logger
from app.entities.value_info import ValueInfo
from app.prompt.prompt_loader import load_prompt


async def recall_value(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """
    字段取值召回节点

    作用：根据用户查询和关键词，从 ES 全文索引中召回匹配的字段取值信息。
    场景举例：用户说"华东地区的销售额"，需要知道"华东"对应的是 region_name 字段的取值，
              这样生成 SQL 时才能写出 WHERE region_name = '华东'。

    与 recall_column 的区别：
        - recall_column：从 Qdrant 向量库召回"有哪些字段"（字段元数据）
        - recall_value：从 ES 全文索引召回"字段的具体取值"（枚举值/业务数据）

    流程：
        1. 用 LLM 扩展关键词，补充语义相关的词
        2. 用扩展后的关键词去 ES 做全文搜索，匹配字段取值
        3. 去重合并结果，返回匹配到的取值列表
    """

    # 推送节点开始执行的进度
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "召回字段取值", "status": "running"})

    # 从 state 中取出用户原始查询和之前提取的关键词
    query = state["query"]
    keywords = state["keywords"]

    # 从 runtime context 获取 ES 仓库（存储字段取值的全文索引）
    value_es_repository = runtime.context["value_es_repository"]

    try:
        # ---- 第一步：LLM 扩展关键词 ----
        # 用户可能只说了"华东"，LLM 会补充"华东地区"、"华东方"等相关词
        # 提高 ES 全文搜索的召回率
        prompt = PromptTemplate(template=load_prompt("extend_keywords_for_value_recall"), input_variables=["query"])
        output_parser = JsonOutputParser()

        # LCEL 链：Prompt -> LLM -> JSON 解析（返回关键词列表）
        chain = prompt | llm | output_parser

        result = await chain.ainvoke({"query": query})

        # ---- 第二步：ES 全文搜索召回字段取值 ----
        # 用 dict 做去重，key 是取值 id，value 是 ValueInfo 对象
        values_map: dict[str, ValueInfo] = {}

        # 合并用户原始关键词和 LLM 扩展的关键词，去重
        keywords = list(set(keywords + result))
        logger.info(f"召回字段取值扩展关键词：{keywords}")

        for keyword in keywords:
            # 在 ES 中做全文搜索，返回与 keyword 匹配的字段取值
            # 例如 keyword="华东" → ValueInfo(id="1", value="华东", column_id="region_name")
            values: list[ValueInfo] = await value_es_repository.search(keyword)
            # 同一个取值可能被多个关键词命中，只保留第一次
            for value in values:
                value_id = value.id
                if value_id not in values_map:
                    values_map[value_id] = value

        retrieved_values = list(values_map.values())

        # 推送成功状态，将召回的取值列表写入 state 供下游使用
        writer({"type": "progress", "step": "召回字段取值", "status": "success"})
        logger.info(f"召回字段取值：{list(values_map.keys())}")

        return {'retrieved_values': retrieved_values}
    except Exception as e:
        writer({"type": "progress", "step": "召回字段取值", "status": "error"})
        logger.error(f"召回字段取值失败: {str(e)}")
        raise
