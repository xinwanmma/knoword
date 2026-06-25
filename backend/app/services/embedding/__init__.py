"""Embedding 服务模块化。

按 model 字符串自动选择 provider：
- "qwen3-embedding:0.6b"              → OllamaProvider
- "shibing624/text2vec-base-chinese"  → HuggingFaceProvider (本地离线)
- "Qwen/Qwen3-Embedding-8B"           → SiliconFlowProvider
- "Qwen/Qwen3-Embedding-4B"           → SiliconFlowProvider
"""
from app.services.embedding.factory import (
    get_embedding_provider, list_available_models, clear_cache,
    close_all_providers,
)

__all__ = [
    "get_embedding_provider", "list_available_models", "clear_cache",
    "close_all_providers",
]
