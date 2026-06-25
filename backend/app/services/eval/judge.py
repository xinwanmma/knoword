"""LLM-as-Judge 评分器 — 固定使用 mimo-v2.5。"""
import json
import logging
import re
from typing import Dict

from app.config import settings
from app.services.llm_provider import get_llm_provider

logger = logging.getLogger(__name__)


JUDGE_PROMPT = """你是 RAG 答案质量评估专家。请基于参考答案评估 AI 回答的质量。

【问题】
{question}

【参考答案】
{ground_truth}

【AI 回答】
{answer}

从三个维度打分（1-5 分）：
1. faithfulness (忠实度): AI 回答是否基于事实，无编造
2. relevance (相关性): AI 回答是否切题
3. completeness (完整度): AI 回答是否覆盖参考答案要点

输出严格的 JSON（不要任何额外说明）：{{"faithfulness": x, "relevance": y, "completeness": z, "reason": "..."}}"""


class LLMJudge:
    """LLM-as-Judge 评分器。固定使用 mimo-v2.5（settings.MIMO_LITE_MODEL）。

    关键约束：
    - Judge 模型永远从 settings.MIMO_LITE_MODEL 创建，不接受外部覆盖
    - 如果 mimo-v2.5 接口失败 → 返回 judge_error 标记，不抛异常
    """

    def __init__(self):
        self._provider = get_llm_provider(settings.MIMO_LITE_MODEL)
        self._llm = self._provider.get_chat_model(temperature=0.1)

    async def score(self, question: str, ground_truth: str, answer: str) -> Dict:
        """调用 mimo-v2.5 对 AI 回答打分。"""
        prompt = JUDGE_PROMPT.format(
            question=question,
            ground_truth=ground_truth,
            answer=answer,
        )
        try:
            response = await self._llm.ainvoke([{"role": "user", "content": prompt}])
            content = response.content if hasattr(response, "content") else str(response)
            return self._parse_json(content)
        except Exception as e:
            logger.error(f"Judge 评分失败: {e}")
            return {
                "faithfulness": 0,
                "relevance": 0,
                "completeness": 0,
                "reason": f"Judge error: {str(e)}",
                "judge_error": True,
            }

    def _parse_json(self, content: str) -> dict:
        """解析 Judge 返回的 JSON（容忍 ```json``` 包裹）。"""
        content = content.strip()
        # 去掉 markdown 代码块
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if match:
            content = match.group(1)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.warning(f"Judge JSON 解析失败: {content[:200]}")
            return {
                "faithfulness": 0,
                "relevance": 0,
                "completeness": 0,
                "reason": f"JSON parse error: {content[:100]}",
                "judge_error": True,
            }
