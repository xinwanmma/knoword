"""GLM 智谱 LLM Provider。"""
from app.config import settings
from app.services.llm_provider.openai_compatible import OpenAICompatibleProvider


class GLMProvider(OpenAICompatibleProvider):
    """智谱 GLM 系列 LLM。

    默认模型：GLM-4.5-flash
    """

    def __init__(self, model: str | None = None):
        super().__init__(
            base_url=settings.GLM_BASE_URL,
            api_key=settings.GLM_API_KEY,
            model=model or settings.GLM_MODEL,
            display_name="GLM",
        )
