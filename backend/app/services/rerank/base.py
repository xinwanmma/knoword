"""Rerank Provider 抽象基类。"""
from abc import ABC, abstractmethod
from typing import List, Tuple


class RerankProvider(ABC):
    """Rerank 提供方统一接口。"""

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @abstractmethod
    async def rerank(
        self,
        query: str,
        documents: List[str],
        top_k: int = 5,
    ) -> List[Tuple[int, float]]:
        """
        返回按相关度降序的 (原始 index, score) 列表。
        原始 index 是 documents 列表中的下标，便于回溯。
        """
        ...
