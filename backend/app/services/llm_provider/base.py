"""LLM Provider 抽象基类。"""
from abc import ABC, abstractmethod
from typing import AsyncIterator


class LLMProvider(ABC):
    """LLM 提供方统一接口（OpenAI 兼容协议）。"""

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @abstractmethod
    def get_chat_model(self, temperature: float | None = None):
        """返回 LangChain ChatModel 实例（用于 LCEL 链）。"""
        ...

    async def astream(self, messages, temperature: float | None = None) -> AsyncIterator[str]:
        """逐 token 流式输出。"""
        chat = self.get_chat_model(temperature=temperature)
        async for chunk in chat.astream(messages):
            if chunk.content:
                yield chunk.content

    async def ainvoke(self, messages, temperature: float | None = None) -> str:
        chat = self.get_chat_model(temperature=temperature)
        result = await chat.ainvoke(messages)
        return result.content
