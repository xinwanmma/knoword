"""LLM 客户端 — 委托给 services.llm_provider.factory。

保留此文件作为兼容入口，新代码请直接使用：
    from app.services.llm_provider import get_llm_provider
    llm = get_llm_provider("mimo-v2.5")
"""
import logging

from app.services.llm_provider.factory import get_llm_provider

logger = logging.getLogger(__name__)


def get_llm(model: str | None = None, temperature: float | None = None):
    """获取 LLM 实例（向后兼容入口）。

    内部委托给 LLM Factory。
    """
    provider = get_llm_provider(model)
    return provider.get_chat_model(temperature=temperature)


def get_llm_for_supervisor():
    """低温度版本（用于路由判断等需要确定性的场景）。"""
    return get_llm(temperature=0.1)
