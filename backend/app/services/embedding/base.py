"""Embedding 提供方抽象基类。"""
from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Embedding 提供方统一接口。"""

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @property
    @abstractmethod
    def dimension(self) -> int: ...

    @abstractmethod
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]: ...

    async def embed_one(self, text: str) -> list[float]:
        """便利方法：单条文本 embedding。"""
        results = await self.embed_documents([text])
        return results[0]
