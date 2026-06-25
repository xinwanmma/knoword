"""RAG 检索流程 — 简化版（无 LangGraph）。

架构（纯函数式）：
1. prepare_sources()：按 KB 策略调用对应 retrieval → 返回 sources
2. chat.py 中直接 llm.astream() 流式生成

不依赖 LangGraph，零状态图，纯函数 + 字典。
"""
import logging
from typing import List

from app.config import settings
from app.services.retrieval import get_retrieval_strategy

logger = logging.getLogger(__name__)


async def prepare_sources(
    query: str,
    kb_ids: List[int],
    search_all: bool = False,
    top_k: int = 5,
    retrieval_strategy: str = "vector",
    embedding_model: str | None = None,
    rerank_model: str | None = None,
    rerank_top_n: int = 20,
) -> list[dict]:
    """准备检索结果（替代 LangGraph prepare 节点）。

    流程：
    1. 选定 retrieval strategy（按 KB 配置）
    2. 执行检索 → top_k 个候选
    3. 格式化为 sources

    Returns:
        sources: [{"doc_id", "filename", "page", "content", "score"}, ...]
    """
    if not kb_ids and not search_all:
        return []

    # 选定 strategy
    strategy = get_retrieval_strategy(
        strategy=retrieval_strategy,
        embedding_model=embedding_model,
        rerank_model=rerank_model,
        rerank_top_n=rerank_top_n,
    )

    # 执行检索
    chunks = await strategy.retrieve(
        query=query,
        kb_ids=kb_ids,
        top_k=top_k,
        search_all=search_all,
    )

    if not chunks:
        return []

    # 格式化（截断 content 长度）
    sources = []
    for c in chunks:
        sources.append({
            "doc_id": c.get("doc_id", 0),
            "filename": c.get("filename", ""),
            "page": c.get("page"),
            "content": c.get("content", "")[:1500],
            "score": c.get("score", 0),
        })

    logger.info(
        f"Prepare done [{retrieval_strategy}]: {len(sources)} sources"
    )
    return sources
