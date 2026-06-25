"""Retrieval 策略模块化。

按 strategy 字符串自动选择：
- "vector"  → VectorRetrieval
- "bm25"    → BM25Retrieval
- "rerank"  → RerankRetrieval (vector + rerank)
- "graph"   → GraphRetrieval (Microsoft GraphRAG, 预留)
"""
from app.services.retrieval.factory import get_retrieval_strategy

__all__ = ["get_retrieval_strategy"]
