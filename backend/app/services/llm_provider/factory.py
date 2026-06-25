"""LLM Factory — 按 model 字符串自动选择 provider。

支持别名解析：
- "mimo-2.5"           → MiMoProvider(model=settings.MIMO_LITE_MODEL)
- "mimo-v2.5-pro"      → MiMoProvider(model=settings.MIMO_MODEL)
- "mimo-2.5-pro"       → MiMoProvider (alias)
- "deepseek-v4-flash"  → DeepSeekProvider
- "GLM-4.5-flash"      → GLMProvider
"""
import logging
from typing import Dict, Type

from app.services.llm_provider.base import LLMProvider
from app.services.llm_provider.deepseek import DeepSeekProvider
from app.services.llm_provider.glm import GLMProvider
from app.services.llm_provider.mimo import MiMoProvider

logger = logging.getLogger(__name__)

# provider 类映射（按 model_id 前缀）
LLM_REGISTRY: Dict[str, Type[LLMProvider]] = {
    "mimo-": MiMoProvider,
    "mimo-2.5-pro": MiMoProvider,
    "mimo-2.5": MiMoProvider,
    "mimo-v2.5-pro": MiMoProvider,
    "deepseek-": DeepSeekProvider,
    "GLM-": GLMProvider,
}

# 模型实例缓存
_instance_cache: Dict[str, LLMProvider] = {}


def get_llm_provider(model_id: str | None = None) -> LLMProvider:
    """根据 model_id 获取（并缓存）LLM provider 实例。

    Args:
        model_id: 模型标识，为 None 时用默认 mimo-v2.5-pro
    """
    from app.config import settings
    model_id = model_id or settings.MIMO_MODEL

    if model_id in _instance_cache:
        return _instance_cache[model_id]

    # 找到匹配的 provider 类
    provider_cls = None
    if model_id in LLM_REGISTRY:
        provider_cls = LLM_REGISTRY[model_id]
    else:
        # 按前缀匹配
        for prefix, cls in LLM_REGISTRY.items():
            if model_id.startswith(prefix):
                provider_cls = cls
                break

    if provider_cls is None:
        available = ", ".join(set(LLM_REGISTRY.keys()))
        raise ValueError(f"未知的 LLM model: {model_id}。可用: {available}")

    # MiMo 的别名处理
    if provider_cls is MiMoProvider and model_id == "mimo-2.5":
        provider = MiMoProvider(model=settings.MIMO_LITE_MODEL)
    elif provider_cls is MiMoProvider and model_id == "mimo-2.5-pro":
        provider = MiMoProvider(model=settings.MIMO_MODEL)
    else:
        provider = provider_cls(model=model_id)

    _instance_cache[model_id] = provider
    logger.info(f"✅ LLM provider 已创建: {model_id}")
    return provider


def list_available_models() -> list[dict]:
    """列出所有可用的 LLM 模型。"""
    return [
        {"id": "mimo-2.5", "provider": "mimo", "type": "cloud"},
        {"id": "mimo-v2.5-pro", "provider": "mimo", "type": "cloud"},
        {"id": "deepseek-v4-flash", "provider": "deepseek", "type": "cloud"},
        {"id": "GLM-4.5-flash", "provider": "glm", "type": "cloud"},
    ]


def clear_cache():
    """清空 provider 缓存。"""
    global _instance_cache
    _instance_cache = {}
