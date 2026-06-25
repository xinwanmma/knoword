"""MiMo LLM Provider — 小米 MiMo 云端 API。"""
from app.config import settings
from app.services.llm_provider.openai_compatible import OpenAICompatibleProvider


class MiMoProvider(OpenAICompatibleProvider):
    """MiMo 官方 LLM。

    支持：mimo-2.5（轻量，用于 Judge）、mimo-v2.5-pro（高级，用于生成）。
    """

    def __init__(self, model: str | None = None):
        super().__init__(
            base_url=settings.MIMO_BASE_URL,
            api_key=settings.MIMO_API_KEY,
            model=model or settings.MIMO_MODEL,
            display_name="MiMo",
        )
