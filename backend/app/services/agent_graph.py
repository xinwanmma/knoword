"""LangGraph 多 Agent 路由系统。

架构：
START → memory_retrieval → supervisor → [rag_agent | general_agent] → memory_update → END

- memory_retrieval: 并行加载三层记忆（Mem0 + Memary + Store）
- supervisor: 用 LLM 判断意图，路由到对应 Agent
- rag_agent: 知识库检索 + 记忆上下文 + LLM 生成
- general_agent: 记忆上下文 + LLM 生成
- memory_update: 对话结束后写入三层记忆
"""

import json
import logging
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import (
    AIMessage, BaseMessage, HumanMessage, SystemMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.config import settings

logger = logging.getLogger(__name__)


# ==================== State 定义 ====================

class AgentState(TypedDict):
    """Agent 图的状态。"""
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    user_name: str
    kb_ids: list[int]
    search_all: bool

    # 三层记忆
    mem0_memories: list[dict]       # Mem0 向量记忆
    graph_context: str              # Memary 图谱上下文
    store_data: dict                # Store 会话状态

    # Agent 输出
    agent_answer: str
    sources: list[dict]
    agent_name: str

    # 原始查询（用于记忆写入）
    original_query: str


# ==================== Agent 工具 ====================

async def _retrieve_documents(query: str, kb_ids: list[int], search_all: bool, user_id: str) -> dict:
    """检索文档 — 使用混合检索（BM25 + 向量）。"""
    from app.services.hybrid_search import hybrid_search

    # 构建过滤条件
    if search_all:
        filter_kb_ids = None
    elif kb_ids:
        filter_kb_ids = kb_ids
    else:
        filter_kb_ids = None

    return await hybrid_search(
        query=query,
        kb_ids=filter_kb_ids,
        n_results=5,
        vector_weight=0.6,
        bm25_weight=0.4,
    )


def _format_sources_text(search_results: dict) -> str:
    """将检索结果格式化为 Prompt 文本。"""
    if not search_results.get("documents"):
        return "(无相关参考资料)"

    lines = []
    for i, (doc_text, meta, dist) in enumerate(
        zip(search_results["documents"], search_results["metadatas"], search_results["distances"])
    ):
        score = round(1 - dist, 4)
        filename = meta.get("filename", "未知文件")
        page = meta.get("page", "?")
        doc_id = meta.get("doc_id", 0)
        lines.append(f"[来源{i+1}] {filename} 第{page}页 (相关度: {score})\n{doc_text}")

    return "\n\n".join(lines)


def _format_memories_text(memories: list[dict], graph_context: str, store_data: dict) -> str:
    """将三层记忆格式化为 Prompt 文本。"""
    parts = []

    # Mem0 记忆
    if memories:
        mem_lines = [f"- {m.get('memory', '')}" for m in memories[:5]]
        parts.append("用户记忆（事实/偏好）：\n" + "\n".join(mem_lines))

    # Memary 图谱
    if graph_context:
        parts.append("用户知识图谱：\n" + graph_context)

    # Store 状态
    if store_data:
        store_lines = [f"- {k}: {v}" for k, v in store_data.items()]
        parts.append("用户会话状态：\n" + "\n".join(store_lines))

    return "\n\n".join(parts) if parts else ""


# ==================== Graph 节点 ====================

def memory_retrieval_node(state: AgentState) -> dict:
    """记忆检索节点：加载三层记忆。

    注意：由于 LangGraph 节点支持同步调用，这里只设置占位。
    实际异步加载在 chat.py 调用前完成，结果通过 state 传入。
    """
    return {
        "mem0_memories": state.get("mem0_memories", []),
        "graph_context": state.get("graph_context", ""),
        "store_data": state.get("store_data", {}),
    }


def supervisor_node(state: AgentState) -> dict:
    """Supervisor 路由节点：用 LLM 判断用户意图。"""
    from app.core.llm import get_llm_for_supervisor

    llm = get_llm_for_supervisor()

    # 获取用户最后一条消息
    messages = state.get("messages", [])
    if not messages:
        return {"agent_name": "general"}

    last_query = messages[-1].content if isinstance(messages[-1], HumanMessage) else str(messages[-1])

    # 构建路由 prompt
    kb_ids = state.get("kb_ids", [])
    search_all = state.get("search_all", False)
    has_kb = bool(kb_ids) or search_all

    route_prompt = f"""你是一个意图分类器。根据用户问题和上下文，决定由哪个 Agent 处理。

可选 Agent：
- rag: 用户提问需要基于知识库/文档回答。当有知识库被选中时优先使用。
- general: 通用对话，闲聊，打招呼，或知识库未覆盖的问题。

当前知识库状态：{"已选择知识库" if has_kb else "未选择知识库"}

用户问题：{last_query}

只回复一个词：rag 或 general"""

    try:
        from langchain_core.messages import HumanMessage as LCHumanMessage
        response = llm.invoke([LCHumanMessage(content=route_prompt)])
        agent_name = response.content.strip().lower()

        if agent_name not in ("rag", "general"):
            agent_name = "rag" if has_kb else "general"

        logger.info(f"Supervisor 路由: '{last_query[:30]}...' → {agent_name}")
        return {"agent_name": agent_name}

    except Exception as e:
        logger.error(f"Supervisor 路由失败: {e}，默认使用 general")
        return {"agent_name": "general"}


async def rag_agent_node(state: AgentState) -> dict:
    """RAG Agent：检索知识库 + 记忆上下文 + LLM 生成。"""
    from app.core.llm import get_llm

    messages = state.get("messages", [])
    if not messages:
        return {"agent_answer": "无消息内容", "sources": []}

    query = state["original_query"]
    kb_ids = state.get("kb_ids", [])
    search_all = state.get("search_all", False)
    user_id = state.get("user_id", "")
    user_name = state.get("user_name", "用户")

    # 检索文档
    search_results = await _retrieve_documents(query, kb_ids, search_all, user_id)
    sources = []

    # 对检索结果进行 Reranking
    candidates = []
    for i, (doc_text, meta, dist) in enumerate(
        zip(
            search_results.get("documents", []),
            search_results.get("metadatas", []),
            search_results.get("distances", []),
        )
    ):
        candidates.append({
            "text": doc_text,
            "metadata": meta,
            "score": round(1 - dist, 4),
        })

    # Reranking（关键词融合快速排序，不依赖 LLM）
    from app.services.reranker import rerank_with_score_fusion
    reranked = await rerank_with_score_fusion(query, candidates, top_n=5)

    for item in reranked:
        meta = item["metadata"]
        sources.append({
            "doc_id": meta.get("doc_id", 0),
            "filename": meta.get("filename", ""),
            "page": meta.get("page"),
            "content": item["text"][:500],
            "score": item.get("rerank_score", item["score"]),
        })

    # 构建 rerank 后的搜索结果用于 prompt
    reranked_search_results = {
        "documents": [r["text"] for r in reranked],
        "metadatas": [r["metadata"] for r in reranked],
        "distances": [1.0 - r.get("rerank_score", r["score"]) for r in reranked],
    }

    # 格式化记忆上下文
    memories_text = _format_memories_text(
        state.get("mem0_memories", []),
        state.get("graph_context", ""),
        state.get("store_data", {}),
    )

    # 格式化检索结果（使用 rerank 后的结果）
    sources_text = _format_sources_text(reranked_search_results)

    # 加载最近 5 轮对话历史
    history_text = ""
    historical = [m for m in messages if not isinstance(m, HumanMessage) or m != messages[-1]]
    recent = historical[-10:]  # 最近 5 轮
    for m in recent:
        role = "用户" if isinstance(m, HumanMessage) else "助手"
        content = m.content[:200] if hasattr(m, 'content') else str(m)[:200]
        history_text += f"{role}: {content}\n"

    # 构建 Prompt
    system_prompt = f"""你是一个知识库问答助手。请根据以下参考资料和用户记忆回答问题。
如果资料中没有相关信息，请如实说明。
请用中文回答，保持准确、简洁、有条理。

{f'''用户记忆：
{memories_text}
''' if memories_text else ''}

参考资料：
{sources_text}

{f'''历史对话：
{history_text}''' if history_text else ''}

用户问题：{query}"""

    llm = get_llm()
    try:
        from langchain_core.messages import HumanMessage as LCHumanMessage, SystemMessage as LCSysMessage
        response = llm.invoke([
            LCSysMessage(content="你是一个知识库问答助手。"),
            LCHumanMessage(content=system_prompt),
        ])
        return {"agent_answer": response.content, "sources": sources}
    except Exception as e:
        logger.error(f"RAG Agent 生成失败: {e}")
        return {"agent_answer": f"生成失败: {e}", "sources": sources}


async def general_agent_node(state: AgentState) -> dict:
    """General Agent：通用对话 + 记忆上下文。"""
    from app.core.llm import get_llm

    messages = state.get("messages", [])
    if not messages:
        return {"agent_answer": "无消息内容", "sources": []}

    query = state["original_query"]
    user_name = state.get("user_name", "用户")

    # 格式化记忆上下文
    memories_text = _format_memories_text(
        state.get("mem0_memories", []),
        state.get("graph_context", ""),
        state.get("store_data", {}),
    )

    # 加载最近对话历史
    history_text = ""
    recent = messages[-10:]
    for m in recent:
        if isinstance(m, HumanMessage):
            history_text += f"用户: {m.content[:200]}\n"
        elif isinstance(m, AIMessage):
            history_text += f"助手: {m.content[:200]}\n"

    system_prompt = f"""你是一个智能助手。请用中文回答问题，保持友好、准确。

{f'''用户记忆：
{memories_text}
''' if memories_text else ''}

{f'''历史对话：
{history_text}''' if history_text else ''}

用户 {user_name} 说：{query}"""

    llm = get_llm()
    try:
        from langchain_core.messages import HumanMessage as LCHumanMessage, SystemMessage as LCSysMessage
        response = llm.invoke([
            LCSysMessage(content="你是一个智能助手。"),
            LCHumanMessage(content=system_prompt),
        ])
        return {"agent_answer": response.content, "sources": []}
    except Exception as e:
        logger.error(f"General Agent 生成失败: {e}")
        return {"agent_answer": f"生成失败: {e}", "sources": []}


def memory_update_node(state: AgentState) -> dict:
    """记忆更新节点：对话结束后写入三层记忆。

    同步占位，实际异步写入在 chat.py 中完成。
    """
    return {}


def route_after_supervisor(state: AgentState) -> str:
    """根据 supervisor 决定路由。"""
    return state.get("agent_name", "general")


# ==================== 构建图 ====================

def build_agent_graph():
    """构建 LangGraph StateGraph。

    使用 MemorySaver checkpointer 持久化 Agent 状态，
    支持断点续传和多轮对话上下文。
    """
    from app.services.checkpoint_service import get_checkpointer

    graph = StateGraph(AgentState)

    # 添加节点
    graph.add_node("memory_retrieval", memory_retrieval_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("rag_agent", rag_agent_node)
    graph.add_node("general_agent", general_agent_node)
    graph.add_node("memory_update", memory_update_node)

    # 添加边
    graph.add_edge(START, "memory_retrieval")
    graph.add_edge("memory_retrieval", "supervisor")

    graph.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {
            "rag": "rag_agent",
            "general": "general_agent",
        },
    )

    graph.add_edge("rag_agent", "memory_update")
    graph.add_edge("general_agent", "memory_update")
    graph.add_edge("memory_update", END)

    # 编译（附带 checkpointer）
    checkpointer = get_checkpointer()
    compiled = graph.compile(checkpointer=checkpointer)
    logger.info("✅ LangGraph Agent 图编译成功（MemorySaver checkpointer 已启用）")
    return compiled


# 延迟编译（导入时不执行）
_compiled_graph = None


def get_compiled_graph():
    """获取编译后的 Agent 图（单例）。"""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_agent_graph()
    return _compiled_graph
