"""LangChain Embeddings 兼容层 — 用 OllamaEmbeddings 封装本地 embedding 模型。"""

from langchain_ollama import OllamaEmbeddings
from app.config import settings


def get_embeddings(model: str | None = None) -> OllamaEmbeddings:
    """获取 LangChain OllamaEmbeddings 实例。

    Args:
        model: 模型名称，默认使用配置中的 embedding 模型

    Returns:
        OllamaEmbeddings 实例
    """
    return OllamaEmbeddings(
        base_url=settings.OLLAMA_BASE_URL,
        model=model or settings.OLLAMA_EMBED_MODEL,
    )
