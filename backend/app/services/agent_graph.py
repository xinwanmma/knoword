"""LangGraph 多 Agent 路由系统（最新 API）。

架构拆分为两阶段：
1. prepare 阶段（非流式）：Store 加载 → Supervisor 路由 → 检索 → 准备上下文
2. generate 阶段（流式）：LLM 用 astream 逐 token 生成

支持特性：
- Store 自动记忆：对话后自动提取用户偏好存入 Store
- Store 权限过滤：从 Store 读取用户权限，过滤无权访问的知识库
- Store 问答缓存：相似问题直接返回缓存答案
"""

import hashlib
import logging
import re
import time
from typing import Annotated, TypedDict

from langchain_core.messages import (
    AIMessage, BaseMessage, HumanMessage, SystemMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.config import settings

logger = logging.getLogger(__name__)

# 预编译正则
_WORD_PATTERN = re.compile(r'[\u4e00-\u9fff]+|\w+')

# 自动记忆提取节流记录
_auto_extract_and_save._last_run: dict[str, float] = {}


# ==================== State 定义 ====================

class AgentState(TypedDict):
    """Agent 图的状态。"""
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    user_name: str
    kb_ids: list[int]
    search_all: bool

    # Store
    store_data: dict

    # 输出
    agent_answer: str
    sources: list[dict]
    agent_name: str
    original_query: str
    from_cache: bool


# ==================== Store 功能 ====================

# Store 内存缓存（60 秒 TTL）
_store_cache: dict[str, tuple[float, dict]] = {}
_STORE_CACHE_TTL = 60  # 秒


def invalidate_store_cache(user_id: str | None = None):
    """清除 Store 内存缓存。

    Args:
        user_id: 指定用户 ID 清除，为 None 时清除全部
    """
    if user_id is None:
        _store_cache.clear()
    else:
        _store_cache.pop(user_id, None)


async def _load_user_store(user_id: str) -> dict:
    """加载用户 Store 数据（带内存缓存）。"""
    import time
    now = time.time()

    # 检查缓存
    if user_id in _store_cache:
        cached_time, cached_data = _store_cache[user_id]
        if now - cached_time < _STORE_CACHE_TTL:
            return cached_data

    # 从数据库加载
    from app.db.database import async_session_factory
    from app.services.store_service import store_get_all

    async with async_session_factory() as db:
        entries = await store_get_all(db, user_id)
    result = {e["key"]: e["value"] for e in entries}

    # 写入缓存
    _store_cache[user_id] = (now, result)
    return result


async def _check_cache(user_id: str, query: str) -> dict | None:
    """检查问答缓存。返回缓存答案或 None。"""
    if not settings.STORE_ENABLED:
        return None

    from app.db.database import async_session_factory
    from app.services.store_service import store_get_all

    async with async_session_factory() as db:
        entries = await store_get_all(db, user_id, namespace="cache")

    # 简单字符串匹配 + 缓存过期检查
    now = time.time()
    ttl = settings.STORE_CACHE_TTL_DAYS * 86400
    threshold = settings.STORE_CACHE_SIMILARITY_THRESHOLD

    for entry in entries:
        cached = entry.get("value", {})
        if not isinstance(cached, dict):
            continue
        cached_query = cached.get("query", "")
        cached_answer = cached.get("answer", "")
        cached_time = cached.get("timestamp", 0)

        # 过期检查
        if now - cached_time > ttl:
            continue

        # 简单相似度：基于关键词重叠
        if _simple_similarity(query, cached_query) >= threshold:
            logger.info(f"Cache hit: '{query[:30]}...' → 有缓存")
            return {"answer": cached_answer, "from_cache": True}

    return None


async def _save_to_cache(user_id: str, query: str, answer: str):
    """保存问答到缓存。"""
    if not settings.STORE_ENABLED:
        return

    from app.db.database import async_session_factory
    from app.services.store_service import store_put

    cache_key = f"cache_{hashlib.md5(query.encode()).hexdigest()[:16]}"
    async with async_session_factory() as db:
        await store_put(db, user_id, cache_key, {
            "query": query,
            "answer": answer,
            "timestamp": time.time(),
        }, namespace="cache")


def _simple_similarity(a: str, b: str) -> float:
    """简单的关键词重叠相似度。"""
    if not a or not b:
        return 0.0
    words_a = set(_WORD_PATTERN.findall(a.lower()))
    words_b = set(_WORD_PATTERN.findall(b.lower()))
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / max(len(words_a), len(words_b))


async def _get_permitted_kb_ids(user_id: str, requested_kb_ids: list[int], search_all: bool) -> list[int]:
    """从 Store 读取权限，过滤知识库 ID。

    返回用户有权限访问的知识库 ID 列表。
    """
    if not settings.STORE_ENABLED:
        return requested_kb_ids

    from app.db.database import async_session_factory
    from app.services.store_service import store_get

    async with async_session_factory() as db:
        entry = await store_get(db, user_id, "permissions")

    if not entry:
        # 没有设置权限，返回原始请求
        return requested_kb_ids

    permitted = entry.get("value", {})
    if isinstance(permitted, dict):
        allowed_kb_ids = permitted.get("kb_ids", [])
    elif isinstance(permitted, list):
        allowed_kb_ids = permitted
    else:
        return requested_kb_ids

    # 取交集
    if search_all:
        return allowed_kb_ids
    return [kb_id for kb_id in requested_kb_ids if kb_id in allowed_kb_ids]


async def _auto_extract_and_save(user_id: str, query: str, answer: str):
    """对话后自动提取用户偏好并存入 Store（带节流）。"""
    if not settings.STORE_ENABLED or not settings.STORE_AUTO_EXTRACT:
        return

    # 节流：短消息不提取
    if len(query) < 15:
        return

    # 节流：每用户每 5 分钟最多一次
    now = time.time()
    _extract_key = f"_last_extract_{user_id}"
    last_run = _auto_extract_and_save._last_run.get(_extract_key, 0)
    if now - last_run < 300:
        return

    try:
        from app.core.llm import get_llm_for_supervisor

        llm = get_llm_for_supervisor()
        prompt = f"""分析以下对话，提取用户的关键信息（姓名、偏好、工作内容、兴趣等）。
只提取明确提到的信息，不要推测。

用户：{query}
助手：{answer[:200]}

以 JSON 格式返回提取的信息，例如：{{"name": "张三", "preference": "..."}}
如果没有值得记住的信息，返回空对象 {{}}。只返回 JSON，不要其他文字。"""

        from langchain_core.messages import HumanMessage
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        content = response.content.strip()

        import json
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        if content.startswith("{"):
            extracted = json.loads(content)
            if extracted:
                from app.db.database import async_session_factory
                from app.services.store_service import store_put

                async with async_session_factory() as db:
                    for key, value in extracted.items():
                        store_key = f"profile_{key}"
                        await store_put(db, user_id, store_key, value, namespace="profile")
                logger.info(f"Auto-extracted profile for user={user_id}: {list(extracted.keys())}")
    except Exception as e:
        logger.error(f"Auto-extract failed: {e}")
    else:
        # LLM 调用成功后才更新节流时间
        _auto_extract_and_save._last_run[_extract_key] = now


# ==================== 准备函数 ====================

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
        lines.append(f"[来源{i+1}] {filename} 第{page}页 (相关度: {score})\n{doc_text}")

    return "\n\n".join(lines)


def _format_store_text(store_data: dict) -> str:
    """将 Store 状态格式化为 Prompt 文本。"""
    if store_data:
        lines = []
        for k, v in store_data.items():
            if not k.startswith("cache_"):  # 不显示缓存数据
                lines.append(f"- {k}: {v}")
        if lines:
            return "用户画像与偏好：\n" + "\n".join(lines)
    return ""


def _build_rag_prompt(
    query: str,
    store_text: str,
    sources_text: str,
    history_text: str,
) -> list:
    """构建 RAG Agent 的消息列表。"""
    system_msg = f"""你是一个知识库问答助手。请根据以下参考资料和用户画像回答问题。
如果资料中没有相关信息，请如实说明。
请用中文回答，保持准确、简洁、有条理。

{f'''{store_text}
''' if store_text else ''}

参考资料：
{sources_text}

{f'''历史对话：
{history_text}''' if history_text else ''}

用户问题：{query}"""

    return [
        SystemMessage(content="你是一个知识库问答助手。"),
        HumanMessage(content=system_msg),
    ]


def _build_general_prompt(
    query: str,
    store_text: str,
    history_text: str,
    user_name: str,
) -> list:
    """构建 General Agent 的消息列表。"""
    system_msg = f"""你是一个智能助手。请用中文回答问题，保持友好、准确。

{f'''{store_text}
''' if store_text else ''}

{f'''历史对话：
{history_text}''' if history_text else ''}

用户 {user_name} 说：{query}"""

    return [
        SystemMessage(content="你是一个智能助手。"),
        HumanMessage(content=system_msg),
    ]


def _format_history(messages: list) -> str:
    """格式化对话历史。"""
    history_text = ""
    recent = messages[-10:]
    for m in recent:
        if isinstance(m, HumanMessage):
            history_text += f"用户: {m.content[:200]}\n"
        elif isinstance(m, AIMessage):
            history_text += f"助手: {m.content[:200]}\n"
    return history_text


# ==================== 图节点 ====================

async def prepare_node(state: AgentState) -> dict:
    """准备阶段：加载 Store → 检查缓存 → Supervisor 路由 → 检索文档。

    非流式，返回完整上下文。
    """
    query = state["original_query"]
    user_id = state["user_id"]
    kb_ids = state.get("kb_ids", [])
    search_all = state.get("search_all", False)

    # 1. 加载 Store
    store_data = await _load_user_store(user_id)

    # 2. 检查问答缓存
    cache_result = await _check_cache(user_id, query)
    if cache_result:
        logger.info(f"Cache hit for user={user_id}: '{query[:30]}...'")
        return {
            "store_data": store_data,
            "agent_answer": cache_result["answer"],
            "sources": [],
            "agent_name": "cache",
            "from_cache": True,
        }

    # 3. 规则路由（不调 LLM，0 延迟）
    permitted_kb_ids = await _get_permitted_kb_ids(user_id, kb_ids, search_all)
    has_kb = bool(permitted_kb_ids) or search_all
    agent_name = "rag" if has_kb else "general"

    sources = []
    search_results = None
    if agent_name == "rag" and (permitted_kb_ids or search_all):
        from app.services.hybrid_search import hybrid_search
        from app.services.reranker import rerank_with_score_fusion

        search_results = await hybrid_search(
            query=query,
            kb_ids=permitted_kb_ids if not search_all else None,
            n_results=5,
        )

        candidates = [
            {"text": d, "metadata": m, "score": round(1 - dist, 4)}
            for d, m, dist in zip(
                search_results.get("documents", []),
                search_results.get("metadatas", []),
                search_results.get("distances", []),
            )
        ]
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

        search_results = {
            "documents": [r["text"] for r in reranked],
            "metadatas": [r["metadata"] for r in reranked],
            "distances": [1.0 - r.get("rerank_score", r["score"]) for r in reranked],
        }

    logger.info(f"Prepare done: agent={agent_name}, cache=False, kb={len(permitted_kb_ids)}")

    return {
        "store_data": store_data,
        "agent_name": agent_name,
        "sources": sources,
        "from_cache": False,
        "kb_ids": permitted_kb_ids,
    }


async def generate_node(state: AgentState) -> dict:
    """生成阶段：用 llm.astream() 逐 token 流式生成。

    这个节点的结果会被外部通过 astream_events 消费。
    """
    agent_name = state.get("agent_name", "general")
    query = state["original_query"]
    store_text = _format_store_text(state.get("store_data", {}))
    messages = state.get("messages", [])
    history_text = _format_history(messages)

    if agent_name == "rag":
        sources_text = _format_sources_text({
            "documents": [s.get("content", "") for s in state.get("sources", [])],
            "metadatas": [{"filename": s.get("filename", ""), "page": s.get("page", "?")} for s in state.get("sources", [])],
            "distances": [1.0 - s.get("score", 0) for s in state.get("sources", [])],
        })
        prompt_messages = _build_rag_prompt(query, store_text, sources_text, history_text)
    else:
        user_name = state.get("user_name", "用户")
        prompt_messages = _build_general_prompt(query, store_text, history_text, user_name)

    from app.core.llm import get_llm
    llm = get_llm()

    # 流式生成：收集完整回答用于后续存储
    full_answer = ""
    async for chunk in llm.astream(prompt_messages):
        if chunk.content:
            full_answer += chunk.content

    return {
        "agent_answer": full_answer,
        "messages": [AIMessage(content=full_answer)],
    }


async def postprocess_node(state: AgentState) -> dict:
    """后处理：缓存问答 + 自动提取记忆。"""
    user_id = state["user_id"]
    query = state["original_query"]
    answer = state.get("agent_answer", "")
    from_cache = state.get("from_cache", False)

    if not from_cache and answer:
        # 保存到缓存
        await _save_to_cache(user_id, query, answer)
        # 自动提取用户偏好
        await _auto_extract_and_save(user_id, query, answer)

    return {}


def route_after_prepare(state: AgentState) -> str:
    """根据 prepare 结果决定路由。"""
    if state.get("from_cache"):
        return "postprocess"
    return "generate"


# ==================== 构建图 ====================

def build_agent_graph():
    """构建 LangGraph StateGraph。

    只包含 prepare 和 postprocess 节点。
    generate（流式 LLM 生成）在 chat.py 中直接处理。
    """
    from app.services.checkpoint_service import get_checkpointer

    graph = StateGraph(AgentState)

    graph.add_node("prepare", prepare_node)
    graph.add_node("postprocess", postprocess_node)

    graph.add_edge(START, "prepare")

    graph.add_conditional_edges(
        "prepare",
        route_after_prepare,
        {
            "postprocess": "postprocess",  # 缓存命中
            "generate": "postprocess",     # 正常流程，chat.py 直接处理 generate
        },
    )

    graph.add_edge("postprocess", END)

    checkpointer = get_checkpointer()
    compiled = graph.compile(checkpointer=checkpointer)
    logger.info("✅ LangGraph Agent 图编译成功")
    return compiled


_compiled_graph = None


def get_compiled_graph():
    """获取编译后的 Agent 图（单例）。"""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_agent_graph()
    return _compiled_graph
