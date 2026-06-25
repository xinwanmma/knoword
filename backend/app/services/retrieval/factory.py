"""Retrieval Factory — 按 strategy 字符串自动选择。"""
import logging
from typing import Dict, Type

from app.services.retrieval.base import RetrievalStrategy
from app.services.retrieval.bm25_retrieval import BM25Retrieval
from app.services.retrieval.graph_retrieval import GraphRetrieval
from app.services.retrieval.rerank_retrieval import RerankRetrieval
from app.services.retrieval.vector_retrieval import VectorRetrieval

logger = logging.getLogger(__name__)

RETRIEVAL_REGISTRY: Dict[str, Type[RetrievalStrategy]] = {
    "vector": VectorRetrieval,
    "bm25": BM25Retrieval,
    "rerank": RerankRetrieval,
    "graph": GraphRetrieval,
}


def get_retrieval_strategy(
    strategy: str = "vector",
    embedding_model: str | None = None,
    rerank_model: str | None = None,
    rerank_top_n: int = 20,
) -> RetrievalStrategy:
    """获取检索策略实例。"""
    if strategy not in RETRIEVAL_REGISTRY:
        available = ", ".join(RETRIEVAL_REGISTRY.keys())
        raise ValueError(f"未知的检索策略: {strategy}。可用: {available}")

    if strategy == "rerank":
        return RerankRetrieval(
            embedding_model=embedding_model,
            rerank_model=rerank_model,
            rerank_top_n=rerank_top_n,
        )
    elif strategy == "graph":
        return GraphRetrieval(embedding_model=embedding_model)
    elif strategy == "bm25":
        return BM25Retrieval()
    else:
        return VectorRetrieval(embedding_model=embedding_model)


def list_available_strategies() -> list[str]:
    return list(RETRIEVAL_REGISTRY.keys())
