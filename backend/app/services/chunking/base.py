"""Chunking 抽象基类。"""
from abc import ABC, abstractmethod


class Chunker(ABC):
    """文档切块策略统一接口。"""

    @property
    @abstractmethod
    def strategy_name(self) -> str: ...

    @abstractmethod
    def split(self, text: str) -> list[str]:
        """将长文本切分为多个块。"""
        ...
