"""LangChain LLM 兼容层 — 用 ChatOllama 封装本地 Ollama 模型。"""

from langchain_ollama import ChatOllama
from app.config import settings


def get_llm(model: str | None = None, temperature: float = 0.7) -> ChatOllama:
    """获取 LangChain ChatOllama 实例。

    Args:
        model: 模型名称，默认使用配置中的 LLM 模型
        temperature: 温度参数

    Returns:
        ChatOllama 实例
    """
    return ChatOllama(
        base_url=settings.OLLAMA_BASE_URL,
        model=model or settings.OLLAMA_LLM_MODEL,
        temperature=temperature,
    )


def get_llm_for_supervisor() -> ChatOllama:
    """Supervisor 路由用的 LLM（低温度，确定性更强）。"""
    return get_llm(temperature=0.1)
