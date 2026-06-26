"""Retrieval Factory — 按 strategy 字符串自动选择。"""
import logging
from typing import Dict, Type

from app.services.retrieval.base import RetrievalStrategy
from app.services.retrieval.hybrid_retrieval import HybridRetrieval
from app.services.retrieval.rerank_retrieval import RerankRetrieval
from app.services.retrieval.vector_retrieval import VectorRetrieval

logger = logging.getLogger(__name__)

RETRIEVAL_REGISTRY: Dict[str, Type[RetrievalStrategy]] = {
    "vector": VectorRetrieval,
    "hybrid": HybridRetrieval,        # vector + BM25 加权融合
    "rerank": RerankRetrieval,        # vector 初筛 + Rerank 重排
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
    elif strategy == "hybrid":
        # Hybrid Fusion: vector + BM25 加权融合（alpha=0.5 平衡）
        return HybridRetrieval(
            embedding_model=embedding_model,
            alpha=0.5,
            top_n_vec=rerank_top_n,    # 复用 rerank_top_n 作为候选数（默认 20）
            top_n_bm25=rerank_top_n,
        )
    else:
        return VectorRetrieval(embedding_model=embedding_model)


def list_available_strategies() -> list[str]:
    return list(RETRIEVAL_REGISTRY.keys())
