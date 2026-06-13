"""LangChain LLM 兼容层 — 用 ChatOllama 封装本地 Ollama 模型。"""

from langchain_ollama import ChatOllama
from app.config import settings

_llm_cache: dict[str, ChatOllama] = {}


def get_llm(model: str | None = None, temperature: float = 0.7) -> ChatOllama:
    """获取 LangChain ChatOllama 实例（带缓存）。"""
    key = f"{model or settings.OLLAMA_LLM_MODEL}_{temperature}"
    if key not in _llm_cache:
        _llm_cache[key] = ChatOllama(
            base_url=settings.OLLAMA_BASE_URL,
            model=model or settings.OLLAMA_LLM_MODEL,
            temperature=temperature,
        )
    return _llm_cache[key]


def get_llm_for_supervisor() -> ChatOllama:
    """Supervisor 路由用的 LLM（低温度）。"""
    return get_llm(temperature=0.1)
