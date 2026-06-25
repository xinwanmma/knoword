"""RAGAS 评估器 — 批量评估 + 指标回填。

RAGAS 提供 6 个核心指标：
- faithfulness: 答案是否基于上下文（防幻觉）
- answer_relevancy: 答案与问题相关度
- context_relevancy: 检索内容与问题相关度
- context_recall: 检索内容覆盖 ground truth 的程度
- context_precision: 检索内容排序质量
- answer_correctness: 答案与 ground truth 语义相似度

使用方式：
- 每个 task 完成后用 LLM-as-Judge（轻量）
- run 结束后批量用 RAGAS（更全面但更慢）
- RAGAS 跑完后把分数回填到 evaluation_results.ragas_scores

关键设计：
- 用 mimo-2.5 作为 RAGAS 用的 LLM（复用 settings.MIMO_LITE_MODEL）
- 用 ollama qwen3-embedding:0.6b 作为 RAGAS 用的 embedding
- RAGAS 一次性把整批数据喂进去，**远快于**逐个样本调用
- 失败时返回空分数，不阻塞整个 run
"""
import logging
import uuid
from typing import List, Dict

from sqlalchemy import select

from app.config import settings
from app.db.database import async_session_factory
from app.models.eval_models import EvaluationResult

logger = logging.getLogger(__name__)


class RagasUnavailableError(Exception):
    """RAGAS 未安装时抛出。"""


def _try_import_ragas():
    """懒加载 RAGAS。"""
    try:
        from ragas import evaluate
        from ragas.metrics import (
            faithfulness,
            answer_relevancy,
            context_relevancy,
            context_recall,
            context_precision,
            answer_correctness,
        )
        from datasets import Dataset
        return {
            "evaluate": evaluate,
            "metrics": [
                faithfulness,
                answer_relevancy,
                context_relevancy,
                context_recall,
                context_precision,
                answer_correctness,
            ],
            "Dataset": Dataset,
        }
    except ImportError as e:
        raise RagasUnavailableError(
            f"RAGAS 未安装: {e}。请运行: pip install ragas datasets"
        )


def _build_ragas_llm():
    """构造 RAGAS 用的 LLM（mimo-2.5）。"""
    from ragas.llms import LangchainLLMWrapper
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        base_url=settings.MIMO_BASE_URL,
        api_key=settings.MIMO_API_KEY,
        model=settings.MIMO_LITE_MODEL,
        temperature=0.0,
    )
    return LangchainLLMWrapper(llm)


def _build_ragas_embeddings():
    """构造 RAGAS 用的 embedding（Ollama qwen3-embedding）。"""
    from ragas.embeddings import LangchainEmbeddingsWrapper
    try:
        from langchain_ollama import OllamaEmbeddings
        emb = OllamaEmbeddings(
            base_url=settings.OLLAMA_BASE_URL,
            model=settings.OLLAMA_EMBED_MODEL,
        )
    except ImportError:
        from langchain_community.embeddings import OllamaEmbeddings
        emb = OllamaEmbeddings(
            base_url=settings.OLLAMA_BASE_URL,
            model=settings.OLLAMA_EMBED_MODEL,
        )
    return LangchainEmbeddingsWrapper(emb)


class RagasEvaluator:
    """RAGAS 批量评估器。"""

    def __init__(self):
        self._llm = None
        self._embeddings = None
        self._ragas_modules = None

    def _ensure_loaded(self):
        """懒加载 RAGAS 及其依赖。"""
        if self._ragas_modules is not None:
            return
        self._ragas_modules = _try_import_ragas()
        self._llm = _build_ragas_llm()
        self._embeddings = _build_ragas_embeddings()

    async def score_run(self, run_id: uuid.UUID) -> dict:
        """对 run 的所有 result 批量跑 RAGAS，回填 ragas_scores 字段。

        Returns:
            汇总 dict: {metric_name: avg_value, ...}
        """
        try:
            self._ensure_loaded()
        except RagasUnavailableError as e:
            logger.error(str(e))
            return {"error": str(e)}

        # 1. 读取所有 result
        async with async_session_factory() as db:
            results = (await db.execute(
                select(EvaluationResult).where(EvaluationResult.run_id == run_id)
            )).scalars().all()

        if not results:
            return {}

        # 2. 构造 RAGAS 输入
        questions = []
        contexts_list = []
        answers = []
        ground_truths = []
        result_ids = []  # 用于回填

        for r in results:
            if r.error_message or not r.generated_answer:
                continue
            questions.append(r.question)
            # contexts: RAGAS 需要 list[list[str]]
            ctxs = [c.get("content", "")[:2000] for c in (r.retrieved_chunks or [])]
            if not ctxs:
                ctxs = [""]  # 避免 RAGAS 报错
            contexts_list.append(ctxs)
            answers.append(r.generated_answer)
            ground_truths.append(r.ground_truth or "")
            result_ids.append(str(r.id))

        if not questions:
            logger.info("RAGAS: 没有可评估的 result")
            return {}

        logger.info(f"RAGAS: 准备评估 {len(questions)} 个样本")

        # 3. 构造 Dataset 并跑评估（同步，丢到线程池）
        ragas_data = {
            "question": questions,
            "contexts": contexts_list,
            "answer": answers,
            "ground_truth": ground_truths,
        }
        Dataset = self._ragas_modules["Dataset"]
        evaluate = self._ragas_modules["evaluate"]
        metrics = self._ragas_modules["metrics"]

        dataset = Dataset.from_dict(ragas_data)

        try:
            import asyncio
            from ragas.run_config import RunConfig
            run_config = RunConfig(
                custom_llm=self._llm,
                custom_embeddings=self._embeddings,
                timeout=120,
            )
            ragas_result = await asyncio.to_thread(
                evaluate,
                dataset,
                metrics=metrics,
                run_config=run_config,
                raise_exceptions=False,
            )
        except Exception as e:
            logger.exception(f"RAGAS 评估失败: {e}")
            return {"error": str(e)}

        # 4. 解析结果
        # ragas_result 是 EvaluationResult 对象，可以转 df
        try:
            df = ragas_result.to_pandas()
        except Exception as e:
            logger.exception(f"转换 RAGAS 结果失败: {e}")
            return {"error": str(e)}

        # 5. 回填到 DB（按 result_id 一一对应）
        metric_names = [
            "faithfulness", "answer_relevancy", "context_relevancy",
            "context_recall", "context_precision", "answer_correctness",
        ]
        async with async_session_factory() as db:
            for idx, result_id in enumerate(result_ids):
                row = (await db.execute(
                    select(EvaluationResult).where(EvaluationResult.id == result_id)
                )).scalar_one_or_none()
                if row is None:
                    continue
                scores = {}
                for m in metric_names:
                    if m in df.columns and idx < len(df):
                        val = df.iloc[idx][m]
                        if val is not None and not (isinstance(val, float) and val != val):  # NaN check
                            try:
                                scores[m] = round(float(val), 4)
                            except (TypeError, ValueError):
                                pass
                if scores:
                    row.ragas_scores = scores
            await db.commit()

        # 6. 汇总
        summary = {}
        for m in metric_names:
            if m in df.columns:
                col = df[m].dropna()
                if len(col) > 0:
                    summary[m] = round(float(col.mean()), 4)
        logger.info(f"RAGAS 评估完成: {summary}")
        return summary

    async def score_one(
        self,
        question: str,
        context: List[str],
        answer: str,
        ground_truth: str,
    ) -> dict:
        """单样本评估（用于实时评估，慢）。"""
        try:
            self._ensure_loaded()
        except RagasUnavailableError as e:
            return {"error": str(e)}

        import asyncio
        ragas_data = {
            "question": [question],
            "contexts": [context],
            "answer": [answer],
            "ground_truth": [ground_truth],
        }
        Dataset = self._ragas_modules["Dataset"]
        evaluate = self._ragas_modules["evaluate"]
        metrics = self._ragas_modules["metrics"]
        dataset = Dataset.from_dict(ragas_data)

        try:
            from ragas.run_config import RunConfig
            run_config = RunConfig(
                custom_llm=self._llm,
                custom_embeddings=self._embeddings,
                timeout=60,
            )
            result = await asyncio.to_thread(
                evaluate, dataset, metrics=metrics, run_config=run_config, raise_exceptions=False
            )
            df = result.to_pandas()
            scores = {}
            for col in df.columns:
                if col in ("question", "contexts", "answer", "ground_truth"):
                    continue
                val = df.iloc[0][col]
                if val is not None:
                    try:
                        scores[col] = round(float(val), 4)
                    except (TypeError, ValueError):
                        pass
            return scores
        except Exception as e:
            logger.warning(f"RAGAS 单样本评估失败: {e}")
            return {"error": str(e)}
