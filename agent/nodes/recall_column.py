from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from agent.context import DataAgentContext
from agent.llm import llm
from agent.state import DataAgentState
from app.core.log import logger
from app.entities.column_info import ColumnInfo
from app.prompt.prompt_loader import load_prompt


async def recall_column(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """
    字段召回节点

    作用：根据用户查询和关键词，从向量数据库中召回相关的字段信息（ColumnInfo）。
    流程：
        1. 用 LLM 对用户原始 query 进行关键词扩展，补充用户可能没提到但语义相关的词
        2. 将扩展后的关键词逐个做 embedding，去 Qdrant 中做向量相似度搜索
        3. 去重合并所有搜索结果，返回匹配到的字段列表
    """

    # 获取流式写入器，用于向前端实时推送节点执行进度
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "召回字段", "status": "running"})

    # 从 state 中取出用户原始查询和 extract_keywords 节点提取的关键词
    query = state["query"]
    keywords = state["keywords"]

    # 从 runtime context 中获取 embedding 客户端和 Qdrant 字段仓库
    # 这些依赖在编译 graph 时通过 context 注入，避免 node 内部自己创建连接
    embedding_client = runtime.context["embedding_client"]
    column_qdrant_repository = runtime.context["column_qdrant_repository"]

    try:
        # ---- 第一步：LLM 扩展关键词 ----
        # 用户输入往往简短（如"华东地区销售额"），直接拿去向量搜索可能召回不全
        # 所以先让 LLM 补充语义相关的关键词（如"区域"、"大区"、"订单金额"等）
        prompt = PromptTemplate(
            template=load_prompt("extend_keywords_for_column_recall"),
            input_variables=["query"],
        )
        output_parser = JsonOutputParser()

        # 构造 LCEL 链：Prompt -> LLM -> JSON解析
        chain = prompt | llm | output_parser

        # 调用 LLM，得到扩展关键词列表（如 ["区域", "省份", "金额"]）
        result = await chain.ainvoke({"query": query})

        # ---- 第二步：向量检索召回字段 ----
        # 用 dict 做去重，key 是字段 id，value 是 ColumnInfo 对象
        retrieved_columns_map: dict[str, ColumnInfo] = {}

        # 合并用户原始关键词和 LLM 扩展的关键词，去重
        keywords = list(set(keywords + result))
        logger.info(f"召回字段信息扩展关键词：{keywords}")

        for keyword in keywords:
            # 将关键词文本转成向量
            embedding = await embedding_client.aembed_query(keyword)
            # 在 Qdrant 中搜索与该向量最相似的字段元数据
            payloads: list[ColumnInfo] = await column_qdrant_repository.search(embedding)
            # 去重：同一个字段可能被多个关键词命中，只保留第一次出现的
            for payload in payloads:
                column_id = payload.id
                if column_id not in retrieved_columns_map:
                    retrieved_columns_map[column_id] = payload

        retrieved_columns = list(retrieved_columns_map.values())

        # 推送成功状态，将召回的字段列表写入 state 供下游节点使用
        writer({"type": "progress", "step": "召回字段", "status": "success"})
        logger.info(f"召回字段信息：{list(retrieved_columns_map.keys())}")
        return {"retrieved_columns": retrieved_columns}
    except Exception as e:
        writer({"type": "progress", "step": "召回字段", "status": "error"})
        logger.error(f"召回字段信息失败: {str(e)}")
        raise
