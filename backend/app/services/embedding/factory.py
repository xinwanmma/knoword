"""Embedding Factory — 按 model 字符串自动选择 provider。"""
import logging
from typing import Dict, Type

from app.services.embedding.base import EmbeddingProvider
from app.services.embedding.huggingface_provider import HuggingFaceProvider
from app.services.embedding.ollama_provider import OllamaProvider
from app.services.embedding.siliconflow_provider import SiliconFlowProvider

logger = logging.getLogger(__name__)

# Provider 注册表
EMBEDDING_REGISTRY: Dict[str, Type[EmbeddingProvider]] = {
    "qwen3-embedding:0.6b": OllamaProvider,
    "shibing624/text2vec-base-chinese": HuggingFaceProvider,
    "Qwen/Qwen3-Embedding-8B": SiliconFlowProvider,
    "Qwen/Qwen3-Embedding-4B": SiliconFlowProvider,
}

# 模型实例缓存
_instance_cache: Dict[str, EmbeddingProvider] = {}


def get_embedding_provider(model_id: str | None = None) -> EmbeddingProvider:
    """根据 model_id 获取（并缓存）embedding provider 实例。

    Args:
        model_id: 模型标识，为 None 时用默认 qwen3-embedding:0.6b
    """
    model_id = model_id or "qwen3-embedding:0.6b"

    # 缓存命中
    if model_id in _instance_cache:
        return _instance_cache[model_id]

    if model_id not in EMBEDDING_REGISTRY:
        available = ", ".join(EMBEDDING_REGISTRY.keys())
        raise ValueError(
            f"未知的 embedding model: {model_id}。可用: {available}"
        )

    provider = EMBEDDING_REGISTRY[model_id]()
    _instance_cache[model_id] = provider
    logger.info(f"✅ Embedding provider 已创建: {model_id}")
    return provider


def list_available_models() -> list[dict]:
    """列出所有可用的 embedding 模型。"""
    return [
        {"id": "qwen3-embedding:0.6b", "provider": "ollama", "type": "local"},
        {"id": "shibing624/text2vec-base-chinese", "provider": "huggingface", "type": "local"},
        {"id": "Qwen/Qwen3-Embedding-8B", "provider": "siliconflow", "type": "cloud"},
        {"id": "Qwen/Qwen3-Embedding-4B", "provider": "siliconflow", "type": "cloud"},
    ]


def clear_cache():
    """清空 provider 缓存（用于测试或多 provider 切换）。"""
    global _instance_cache
    _instance_cache = {}


async def close_all_providers():
    """关闭所有已缓存的 provider（应用退出时调用）。"""
    for model_id, provider in list(_instance_cache.items()):
        aclose = getattr(provider, "aclose", None)
        if aclose is not None:
            try:
                result = aclose()
                # 兼容同步和异步 aclose
                if hasattr(result, "__await__"):
                    await result
                logger.info(f"✅ Embedding provider 已关闭: {model_id}")
            except Exception as e:
                logger.warning(f"⚠️  关闭 embedding provider 失败: {model_id} - {e}")
    _instance_cache.clear()
