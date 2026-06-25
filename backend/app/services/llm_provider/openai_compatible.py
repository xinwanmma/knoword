"""LLM Provider 通用基类 — OpenAI 兼容协议。

所有 LLM provider（MiMo / DeepSeek / GLM）都是 OpenAI 兼容协议，
只需要 base_url + api_key + model 三个参数。
"""
from langchain_openai import ChatOpenAI

from app.services.llm_provider.base import LLMProvider


class OpenAICompatibleProvider(LLMProvider):
    """OpenAI 兼容协议的 LLM Provider 基类。"""

    def __init__(self, base_url: str, api_key: str, model: str, display_name: str | None = None):
        if not api_key:
            raise RuntimeError(
                f"{display_name or model} 的 API_KEY 未配置！请在 backend/.env 中设置。"
            )
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._display_name = display_name or model

    @property
    def model_name(self) -> str:
        return self._model

    def get_chat_model(self, temperature: float | None = None):
        from app.config import settings
        return ChatOpenAI(
            base_url=self._base_url,
            api_key=self._api_key,
            model=self._model,
            temperature=temperature if temperature is not None else settings.MIMO_LLM_TEMPERATURE,
            timeout=120.0,
            max_retries=2,
        )
