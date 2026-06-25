"""Retrieval 策略抽象基类。"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any


class RetrievalStrategy(ABC):
    """检索策略统一接口。"""

    @property
    @abstractmethod
    def strategy_name(self) -> str: ...

    @abstractmethod
    async def retrieve(
        self,
        query: str,
        kb_ids: List[int],
        top_k: int = 5,
        search_all: bool = False,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """返回候选 chunk 列表，按相关度降序。

        Returns:
            [{"chunk_id", "doc_id", "filename", "page", "content", "score"}, ...]
        """
        ...
