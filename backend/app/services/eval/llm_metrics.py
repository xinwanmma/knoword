"""3 个 LLM 评估指标（LangChain 风格）。

指标：
1. **Faithfulness / Groundedness** — 拆 answer → statements → 每个是否由 context 推出
2. **Answer Relevancy** — LLM judge 0/1
3. **Answer Correctness** — F1 + embedding cos sim 0.5/0.5

模型：默认 `settings.MIMO_MODEL`（可在 .env 改），评估启动时可由 `llm_metric_model` 覆盖
并发：用 LangChain `RunnableParallel` 跑 3 个指标

每个指标返回 0-1 分数（None 表示评估失败或被禁用）。
"""
import asyncio
import json
import logging
import re
from typing import List, Dict, Optional, Set

import numpy as np
from langchain_core.runnables import Runnable, RunnableParallel, RunnableLambda
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import settings
from app.services.embedding import get_embedding_provider
from app.services.eval.prompts import (
    STATEMENT_EXTRACTION_PROMPT,
    FAITHFULNESS_VERDICT_PROMPT,
    ANSWER_RELEVANCY_PROMPT,
)

logger = logging.getLogger(__name__)


# 3 个 LLM 指标的标准 key
STANDARD_LLM_KEYS: tuple[str, ...] = (
    "faithfulness", "answer_relevancy", "answer_correctness",
)


# ===== 工具函数 =====

def _build_judge_llm(model_name: Optional[str] = None):
    """构造评估用的 LLM（默认 settings.MIMO_MODEL，调用方可覆盖）。"""
    from langchain_openai import ChatOpenAI
    if not settings.MIMO_API_KEY:
        raise RuntimeError("MIMO_API_KEY 未配置，无法跑 LLM 评估")
    return ChatOpenAI(
        base_url=settings.MIMO_BASE_URL,
        api_key=settings.MIMO_API_KEY,
        model=model_name or settings.MIMO_MODEL,
        temperature=0.0,  # 评估要稳
        timeout=120.0,
        max_retries=2,
    )


def _parse_json(text: str) -> dict | list | None:
    """鲁棒地解析 LLM 返回的 JSON（容忍 markdown fence、前后杂质）。"""
    if not text:
        return None
    text = text.strip()
    # 去掉 ```json ... ``` 包裹
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    # 找第一个 {...} 或 [...]
    m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            return None
    return None


async def _ainvoke_json(chain, inputs: dict) -> dict | list | None:
    """调 LangChain chain 并解析 JSON 输出。"""
    try:
        msg = await chain.ainvoke(inputs)
        content = msg.content if hasattr(msg, "content") else str(msg)
        return _parse_json(content)
    except Exception as e:
        logger.warning(f"LLM 评估调用失败: {e}")
        return None


# ===== 1. Faithfulness =====

async def compute_faithfulness(
    *,
    answer: str,
    contexts: List[str],
    llm,
) -> Optional[float]:
    """Faithfulness: 拆 statements → 逐个 verdict → 平均 grounded 比例。

    0-1，越高越 grounded。
    返回 None 表示评估失败。
    """
    if not answer or not answer.strip():
        return 0.0
    if not contexts:
        return 0.0

    # Step 1: 拆 statements
    extract_chain = STATEMENT_EXTRACTION_PROMPT | llm
    parsed = await _ainvoke_json(extract_chain, {"answer": answer})
    if not parsed or "statements" not in parsed:
        logger.warning("Faithfulness: statement 拆解失败")
        return None
    statements = [s.strip() for s in parsed["statements"] if s and s.strip()]
    if not statements:
        return 0.0

    # Step 2: 逐个 verdict（并发）
    contexts_str = "\n\n".join(contexts)
    verdict_chain = FAITHFULNESS_VERDICT_PROMPT | llm
    tasks = [
        _ainvoke_json(verdict_chain, {"statement": s, "contexts": contexts_str})
        for s in statements
    ]
    verdicts = await asyncio.gather(*tasks)

    # Step 3: 计算 grounded 比例
    grounded = 0
    total = 0
    for v in verdicts:
        if v and isinstance(v.get("verdict"), (int, float)):
            grounded += int(v["verdict"])
            total += 1
    if total == 0:
        return None
    return round(grounded / total, 4)


# ===== 2. Answer Relevancy =====

async def compute_answer_relevancy(
    *,
    question: str,
    answer: str,
    llm,
) -> Optional[float]:
    """Answer Relevancy: LLM judge 0/0.5/1。

    0-1，越高越切题。
    """
    if not answer or not answer.strip():
        return 0.0
    if not question or not question.strip():
        return None

    chain = ANSWER_RELEVANCY_PROMPT | llm
    parsed = await _ainvoke_json(chain, {"question": question, "answer": answer})
    if not parsed or "score" not in parsed:
        return None
    try:
        score = float(parsed["score"])
        return round(max(0.0, min(1.0, score)), 4)
    except (TypeError, ValueError):
        return None


# ===== 3. Answer Correctness =====

def _tokenize(text: str) -> List[str]:
    """简单分词：中文按字符 + 英文按 word。"""
    # 把英文/数字串保留为 token，中文逐字符
    return re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9]+", text or "")


def _token_f1(a: str, b: str) -> float:
    """Token F1（不分大小写）。"""
    ta = set(_tokenize(a.lower()))
    tb = set(_tokenize(b.lower()))
    if not ta or not tb:
        return 0.0
    common = ta & tb
    precision = len(common) / len(ta)
    recall = len(common) / len(tb)
    if precision + recall == 0:
        return 0.0
    return round(2 * precision * recall / (precision + recall), 4)


async def _embedding_similarity(a: str, b: str) -> Optional[float]:
    """用 settings.OLLAMA_EMBED_MODEL 算 cos 相似度。"""
    if not a or not b:
        return 0.0
    try:
        provider = get_embedding_provider(settings.OLLAMA_EMBED_MODEL)
    except Exception as e:
        logger.warning(f"Answer Correctness: embedding provider 失败: {e}")
        return None
    try:
        # embed_query 是 async coroutine，直接 await（Ollama 是 HTTP 但已经是 async 封装）
        va, vb = await asyncio.gather(
            provider.embed_query(a),
            provider.embed_query(b),
        )
        va_arr, vb_arr = np.array(va), np.array(vb)
        denom = (np.linalg.norm(va_arr) * np.linalg.norm(vb_arr))
        if denom == 0:
            return 0.0
        return round(float(np.dot(va_arr, vb_arr) / denom), 4)
    except Exception as e:
        logger.warning(f"Answer Correctness: embedding 调用失败: {e}")
        return None


async def compute_answer_correctness(
    *,
    answer: str,
    ground_truth: str,
) -> Optional[float]:
    """Answer Correctness: 0.5 * F1 + 0.5 * embedding_cos_sim。"""
    if not ground_truth or not ground_truth.strip():
        return None
    if not answer or not answer.strip():
        return 0.0

    f1 = _token_f1(answer, ground_truth)
    sem_sim = await _embedding_similarity(answer, ground_truth)
    if sem_sim is None:
        # 兜底只用 F1
        return round(f1, 4)
    return round(0.5 * f1 + 0.5 * sem_sim, 4)


# ===== 批量并发跑 3 个指标 =====

async def compute_all_llm_metrics(
    *,
    question: str,
    answer: str,
    contexts: List[str],
    ground_truth: str = "",
    enabled: Optional[Set[str]] = None,
    llm_model: Optional[str] = None,
) -> Dict[str, Optional[float]]:
    """并发跑 3 个 LLM 指标，返回 {name: score}。

    每个 score 是 0-1，None 表示评估失败或被禁用。
    enabled：仅跑集合内的指标（None = 全跑 3 个）
    llm_model：覆盖默认 judge LLM（None = settings.MIMO_MODEL）
    """
    keys = set(enabled) if enabled is not None else set(STANDARD_LLM_KEYS)
    keys &= set(STANDARD_LLM_KEYS)

    # 全部禁用 → 立即返回 3 个 None
    if not keys:
        return {k: None for k in STANDARD_LLM_KEYS}

    # 3 个指标独立计算，按 enabled 跳过
    faithfulness_coro = (
        compute_faithfulness(
            answer=answer, contexts=contexts,
            llm=_build_judge_llm(llm_model),
        )
        if "faithfulness" in keys else _noop()
    )
    relevancy_coro = (
        compute_answer_relevancy(
            question=question, answer=answer,
            llm=_build_judge_llm(llm_model),
        )
        if "answer_relevancy" in keys else _noop()
    )
    correctness_coro = (
        compute_answer_correctness(answer=answer, ground_truth=ground_truth)
        if "answer_correctness" in keys else _noop()
    )

    faithfulness, relevancy, correctness = await asyncio.gather(
        faithfulness_coro, relevancy_coro, correctness_coro,
    )
    return {
        "faithfulness": faithfulness if "faithfulness" in keys else None,
        "answer_relevancy": relevancy if "answer_relevancy" in keys else None,
        "answer_correctness": correctness if "answer_correctness" in keys else None,
    }


async def _noop() -> None:
    """占位 coroutine，用于跳过未启用指标。"""
    return None


# ===== LangChain Runnable 风格封装（可选）=====

class LLMEvalRunnable(Runnable):
    """LangChain Runnable 风格的 LLM 评估器。

    用法：
        runner = LLMEvalRunnable(llm_model="mimo-v2.5", enabled={"faithfulness", "answer_relevancy"})
        result = await runner.ainvoke({
            "question": ..., "answer": ..., "contexts": [...], "ground_truth": ...
        })
        # result = {"faithfulness": 0.8, "answer_relevancy": 1.0, "answer_correctness": None}
    """

    def __init__(
        self,
        *,
        llm_model: Optional[str] = None,
        enabled: Optional[Set[str]] = None,
    ):
        self._llm_model = llm_model
        self._enabled = enabled

    def invoke(self, input: dict, config=None, **kwargs) -> dict:
        return asyncio.run(self._acall(input))

    async def ainvoke(self, input: dict, config=None, **kwargs) -> dict:
        return await self._acall(input)

    async def _acall(self, input: dict) -> dict:
        return await compute_all_llm_metrics(
            question=input.get("question", ""),
            answer=input.get("answer", ""),
            contexts=input.get("contexts", []),
            ground_truth=input.get("ground_truth", ""),
            enabled=self._enabled,
            llm_model=self._llm_model,
        )


def build_parallel_eval_chain(
    *,
    llm_model: Optional[str] = None,
    enabled: Optional[Set[str]] = None,
) -> Runnable:
    """构造 RunnableParallel 风格的 3 指标并发 chain。

    用法：
        chain = build_parallel_eval_chain(llm_model="mimo-v2.5", enabled={"faithfulness"})
        result = await chain.ainvoke({
            "question": ..., "answer": ..., "contexts": [...], "ground_truth": ...
        })
    """
    keys = set(enabled) if enabled is not None else set(STANDARD_LLM_KEYS)
    keys &= set(STANDARD_LLM_KEYS)

    def _maybe(coro_factory, key: str):
        """按 enabled 决定是否构造 runnable。"""
        if key in keys:
            return RunnableLambda(coro_factory)
        return RunnableLambda(lambda inp: _noop())

    return RunnableParallel(
        faithfulness=_maybe(
            lambda inp: compute_faithfulness(
                answer=inp["answer"], contexts=inp["contexts"],
                llm=_build_judge_llm(llm_model),
            ),
            "faithfulness",
        ),
        answer_relevancy=_maybe(
            lambda inp: compute_answer_relevancy(
                question=inp["question"], answer=inp["answer"],
                llm=_build_judge_llm(llm_model),
            ),
            "answer_relevancy",
        ),
        answer_correctness=_maybe(
            lambda inp: compute_answer_correctness(
                answer=inp["answer"], ground_truth=inp.get("ground_truth", ""),
            ),
            "answer_correctness",
        ),
    )
