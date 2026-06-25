"""Rerank Provider 模块化。

按 model 字符串自动选择：
- "BAAI/bge-reranker-base"   → HuggingFaceRerankProvider (本地离线)
- "Qwen/Qwen3-Reranker-4B"   → SiliconFlowRerankProvider
"""
from app.services.rerank.factory import (
    get_rerank_provider, list_available_models, clear_cache,
)

__all__ = ["get_rerank_provider", "list_available_models", "clear_cache"]
