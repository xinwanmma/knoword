"""DeepSeek LLM Provider。"""
from app.config import settings
from app.services.llm_provider.openai_compatible import OpenAICompatibleProvider


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek 官方 LLM。

    默认模型：deepseek-v4-flash
    """

    def __init__(self, model: str | None = None):
        super().__init__(
            base_url=settings.DEEPSEEK_BASE_URL,
            api_key=settings.DEEPSEEK_API_KEY,
            model=model or settings.DEEPSEEK_MODEL,
            display_name="DeepSeek",
        )
