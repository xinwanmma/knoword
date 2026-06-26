"""Retrieval 策略模块化。

按 strategy 字符串自动选择：
- "vector"  → VectorRetrieval（纯向量 ANN）
- "hybrid"  → HybridRetrieval（vector + BM25 加权融合）
- "rerank"  → RerankRetrieval（vector 初筛 + Rerank 重排）
"""
from app.services.retrieval.factory import get_retrieval_strategy

__all__ = ["get_retrieval_strategy"]
