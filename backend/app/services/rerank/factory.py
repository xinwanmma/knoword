"""Rerank Factory — 按 model 字符串自动选择 provider。"""
import logging
from typing import Dict, Type

from app.services.rerank.base import RerankProvider
from app.services.rerank.huggingface_provider import HuggingFaceRerankProvider
from app.services.rerank.siliconflow_provider import SiliconFlowRerankProvider

logger = logging.getLogger(__name__)

RERANK_REGISTRY: Dict[str, Type[RerankProvider]] = {
    "BAAI/bge-reranker-base": HuggingFaceRerankProvider,
    "Qwen/Qwen3-Reranker-4B": SiliconFlowRerankProvider,
}

_instance_cache: Dict[str, RerankProvider] = {}


def get_rerank_provider(model_id: str | None = None) -> RerankProvider:
    """根据 model_id 获取 rerank provider。"""
    from app.config import settings
    model_id = model_id or settings.HF_RERANK_MODEL

    if model_id in _instance_cache:
        return _instance_cache[model_id]

    if model_id not in RERANK_REGISTRY:
        available = ", ".join(RERANK_REGISTRY.keys())
        raise ValueError(f"未知的 rerank model: {model_id}。可用: {available}")

    provider = RERANK_REGISTRY[model_id]()
    _instance_cache[model_id] = provider
    logger.info(f"✅ Rerank provider 已创建: {model_id}")
    return provider


def list_available_models() -> list[dict]:
    return [
        {"id": "BAAI/bge-reranker-base", "provider": "huggingface", "type": "local"},
        {"id": "Qwen/Qwen3-Reranker-4B", "provider": "siliconflow", "type": "cloud"},
    ]


def clear_cache():
    global _instance_cache
    _instance_cache = {}
