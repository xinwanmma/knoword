"""评估运行器 — 核心执行引擎。

关键设计：
1. **细粒度持久化**：每个 task 一完成就 commit，绝不在内存中累积
2. **断点续传**：启动时查询已完成 task，只跑未完成的
3. **并行执行**：asyncio.Semaphore 控制并发（默认 4）
4. **可取消**：用户停止时优雅退出，已完成结果全部保留
5. **独立 session**：每个 task 独立 session，避免连接池耗尽

评估指标（每次都默认跑，**无开关**）：
- 检索指标（5 个，纯算法）：Recall@K / Precision@K / Hit@K / MRR / NDCG@K
- LLM 指标（3 个，基于 LangChain）：
  - Faithfulness / Groundedness（基于 retrieved contexts 验证）
  - Answer Relevancy（LLM judge 0/0.5/1）
  - Answer Correctness（F1 + embedding cos sim）
- LLM 评估模型：settings.MIMO_LITE_MODEL（可在 .env 改）
"""
import asyncio
import logging
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import List

from sqlalchemy import select

from app.config import settings
from app.db.database import async_session_factory
from app.models.eval_models import EvaluationDataset, EvaluationResult, EvaluationRun
from app.models.models import KnowledgeBase
from app.services.embedding import get_embedding_provider
from app.services.eval.llm_metrics import compute_all_llm_metrics
from app.services.eval.metrics import compute_retrieval_metrics
from app.services.eval.report import ReportGenerator
from app.services.llm_provider import get_llm_provider
from app.services.rerank import get_rerank_provider
from app.services.retrieval import get_retrieval_strategy

logger = logging.getLogger(__name__)


class EvalRunner:
    """评估运行器。"""

    def __init__(self, run_id: uuid.UUID):
        self.run_id = run_id
        self._stop_flag = asyncio.Event()
        self._semaphore = asyncio.Semaphore(settings.DEFAULT_EVAL_CONCURRENCY)

    def request_stop(self):
        """用户点击「停止评估」时调用。"""
        self._stop_flag.set()
        logger.info(f"EvalRun {self.run_id}: 收到停止信号")

    async def start(self):
        """由 API 层调用：asyncio.create_task(runner.start())。"""
        try:
            await self._run()
        except Exception as e:
            logger.exception(f"EvalRun {self.run_id} 异常: {e}")
            await self._mark_run_status("failed", error=str(e))

    # ====== 核心流程 ======

    async def _run(self):
        # 1. 读 run + dataset
        async with async_session_factory() as db:
            run = (await db.execute(
                select(EvaluationRun).where(EvaluationRun.id == self.run_id)
            )).scalar_one()
            dataset = (await db.execute(
                select(EvaluationDataset).where(EvaluationDataset.id == run.dataset_id)
            )).scalar_one()

        # 1.5 获取 KB 绑定的 embedding model（物理上不能换）
        # ChromaDB collection 维度在 document 写入时已锁定，
        # 评估检索必须用 KB 绑定的 embedding model，否则 dimension mismatch
        kb_embedding_model = await self._get_kb_embedding_model(dataset.kb_id)
        requested_embedding_models = (run.config or {}).get("embedding_models", [])
        if (kb_embedding_model
                and requested_embedding_models
                and kb_embedding_model not in requested_embedding_models):
            logger.warning(
                f"评估请求的 embedding_models={requested_embedding_models}，"
                f"但 KB {dataset.kb_id} 绑定的是 {kb_embedding_model}。"
                f"将强制使用 KB 绑定的 embedding（ChromaDB collection 维度已锁定）。"
            )

        # 2. 展开 task（用 KB 绑定的 embedding model）
        all_tasks = self._expand_tasks(
            dataset.qa_pairs, run.config, kb_embedding_model
        )
        async with async_session_factory() as db:
            run = (await db.execute(
                select(EvaluationRun).where(EvaluationRun.id == self.run_id)
            )).scalar_one()
            run.total_tasks = len(all_tasks)
            if run.status == "pending":
                run.status = "running"
                run.started_at = datetime.now(timezone.utc)
            await db.commit()

        # 3. 断点续传：过滤已完成 task
        completed_keys = await self._get_completed_task_keys()
        pending_tasks = [t for t in all_tasks if self._task_key(t) not in completed_keys]
        logger.info(
            f"EvalRun {self.run_id}: 总 {len(all_tasks)}, "
            f"已完成 {len(all_tasks) - len(pending_tasks)}, "
            f"待跑 {len(pending_tasks)}"
        )

        # 4. 并发执行
        coros = [self._run_with_limit(t) for t in pending_tasks]
        await asyncio.gather(*coros, return_exceptions=True)

        # 5. 检查是否被停止
        if self._stop_flag.is_set():
            await self._mark_run_status("stopped")
            return

        # 6. 汇总 + 生成报告
        await self._finalize_run()

    def _expand_tasks(
        self, qa_pairs: list, config: dict, kb_embedding_model: str | None = None
    ) -> list[dict]:
        """展开笛卡尔积：每个 (qa × embedding × retrieval × rerank × generation) 一个 task。

        关键：embedding_models 被强制替换为 [kb_embedding_model]（ChromaDB 维度已锁），
        用户请求的列表保留在 config.requested_embedding_models 里给报告参考。
        """
        retrievals = config.get("retrieval_strategies", [])
        generations = config.get("generation_models", [])
        rerank_models = config.get("rerank_models", [])

        # 强制用 KB 绑定的 embedding model（兜底用 settings 默认值）
        embed_models = [kb_embedding_model or settings.OLLAMA_EMBED_MODEL]

        tasks = []
        for qa_idx, qa in enumerate(qa_pairs):
            for em in embed_models:
                for rt in retrievals:
                    if rt == "rerank" and rerank_models:
                        for rm in rerank_models:
                            for gm in generations:
                                tasks.append({
                                    "qa_index": qa_idx,
                                    "question": qa["question"],
                                    "ground_truth": qa["ground_truth"],
                                    "source_chunk_ids": qa.get("source_chunk_ids", []),
                                    "source_doc_ids": qa.get("source_doc_ids", []),
                                    "embedding_model": em,
                                    "retrieval_strategy": rt,
                                    "rerank_model": rm,
                                    "generation_model": gm,
                                })
                    else:
                        for gm in generations:
                            tasks.append({
                                "qa_index": qa_idx,
                                "question": qa["question"],
                                "ground_truth": qa["ground_truth"],
                                "source_chunk_ids": qa.get("source_chunk_ids", []),
                                "source_doc_ids": qa.get("source_doc_ids", []),
                                "embedding_model": em,
                                "retrieval_strategy": rt,
                                "rerank_model": None,
                                "generation_model": gm,
                            })
        return tasks

    async def _get_kb_embedding_model(self, kb_id: int) -> str | None:
        """读 KB 绑定的 embedding model。"""
        async with async_session_factory() as db:
            kb = (await db.execute(
                select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
            )).scalar_one_or_none()
            return kb.embedding_model if kb else None

    @staticmethod
    def _task_key(t: dict) -> str:
        return (
            f"{t['qa_index']}|{t['embedding_model']}|"
            f"{t['retrieval_strategy']}|{t.get('rerank_model') or '-'}|"
            f"{t['generation_model']}"
        )

    async def _get_completed_task_keys(self) -> set[str]:
        async with async_session_factory() as db:
            result = await db.execute(
                select(EvaluationResult).where(EvaluationResult.run_id == self.run_id)
            )
            rows = result.scalars().all()
            return {self._task_key({
                "qa_index": r.qa_index,
                "embedding_model": r.embedding_model,
                "retrieval_strategy": r.retrieval_strategy,
                "rerank_model": r.rerank_model,
                "generation_model": r.generation_model,
            }) for r in rows}

    async def _run_with_limit(self, task: dict):
        """信号量保护 + 立即写库。"""
        if self._stop_flag.is_set():
            return
        async with self._semaphore:
            if self._stop_flag.is_set():
                return
            try:
                result = await self._run_single_task(task)
                await self._save_result(result)
                await self._update_progress()
            except Exception as e:
                logger.exception(f"Task 失败: {task.get('qa_index')}, err={e}")
                await self._save_error_result(task, str(e))

    async def _run_single_task(self, task: dict) -> dict:
        """执行单个 task：检索 → 5 检索指标 → 生成 → 3 LLM 指标。"""
        start = time.time()

        # 1. 检索（按 embedding_model + retrieval_strategy 路由）
        strategy = get_retrieval_strategy(
            strategy=task["retrieval_strategy"],
            embedding_model=task["embedding_model"],
            rerank_model=task.get("rerank_model"),
        )
        # KB IDs：默认用配置中的所有 KB（评估时简化处理：检索整个数据集 KB）
        kb_ids = await self._get_kb_ids_for_task(task)
        chunks = await strategy.retrieve(
            query=task["question"],
            kb_ids=kb_ids,
            top_k=5,
            search_all=not kb_ids,
        )
        retrieved_ids = [c.get("chunk_id", "") for c in chunks]

        # 2. 生成（按 generation_model 调用对应 LLM）
        provider = get_llm_provider(task["generation_model"])
        llm = provider.get_chat_model(temperature=0.5)
        context = "\n\n".join(c.get("content", "")[:800] for c in chunks[:3])
        prompt_text = (
            f"基于以下参考资料回答问题。如果资料不足，请说明。\n\n"
            f"【参考资料】\n{context}\n\n【问题】\n{task['question']}"
        )
        response = await llm.ainvoke([{"role": "user", "content": prompt_text}])
        answer = response.content if hasattr(response, "content") else str(response)

        # 3. 5 个标准检索指标（纯算法）
        ret_metrics = compute_retrieval_metrics(
            retrieved_ids, task.get("source_chunk_ids", []), k=5
        )

        # 4. 3 个 LLM 指标（Faithfulness / Answer Relevancy / Answer Correctness）
        #    用 LangChain RunnableParallel 风格并发跑，模型 = settings.MIMO_LITE_MODEL
        try:
            llm_scores = await compute_all_llm_metrics(
                question=task["question"],
                answer=answer,
                contexts=[c.get("content", "") for c in chunks[:5]],
                ground_truth=task.get("ground_truth", "") or "",
            )
            # llm_scores = {faithfulness, answer_relevancy, answer_correctness}
            # 任一为 None → judge_error = True（复用旧字段避免改 schema）
            judge_error = any(v is None for v in llm_scores.values())
        except Exception as e:
            logger.exception(f"LLM 指标评估失败: {e}")
            llm_scores = {
                "faithfulness": None,
                "answer_relevancy": None,
                "answer_correctness": None,
            }
            judge_error = True

        latency = int((time.time() - start) * 1000)
        return {
            "qa_index": task["qa_index"],
            "question": task["question"],
            "ground_truth": task["ground_truth"],
            "embedding_model": task["embedding_model"],
            "retrieval_strategy": task["retrieval_strategy"],
            "rerank_model": task.get("rerank_model"),
            "generation_model": task["generation_model"],
            "retrieved_chunks": chunks[:5],
            "generated_answer": answer,
            "retrieval_metrics": ret_metrics,
            "generation_scores": llm_scores,
            "judge_error": judge_error,
            "latency_ms": latency,
        }

    async def _get_kb_ids_for_task(self, task: dict) -> List[int]:
        """评估时获取 run 关联的 KB 列表。"""
        async with async_session_factory() as db:
            run = (await db.execute(
                select(EvaluationRun).where(EvaluationRun.id == self.run_id)
            )).scalar_one()
            dataset = (await db.execute(
                select(EvaluationDataset).where(EvaluationDataset.id == run.dataset_id)
            )).scalar_one()
            return [dataset.kb_id]

    async def _save_result(self, result: dict):
        """每个 result 完成后立即 insert。"""
        async with async_session_factory() as db:
            row = EvaluationResult(
                id=uuid.uuid4(),
                run_id=self.run_id,
                **result,
            )
            db.add(row)
            await db.commit()

    async def _save_error_result(self, task: dict, error: str):
        async with async_session_factory() as db:
            row = EvaluationResult(
                id=uuid.uuid4(),
                run_id=self.run_id,
                qa_index=task["qa_index"],
                question=task.get("question"),
                ground_truth=task.get("ground_truth"),
                embedding_model=task["embedding_model"],
                retrieval_strategy=task["retrieval_strategy"],
                rerank_model=task.get("rerank_model"),
                generation_model=task["generation_model"],
                error_message=error[:1000],
            )
            db.add(row)
            await db.commit()
        # 错误 task 也算"完成"（便于进度准确），但 progress 不算它
        await self._update_progress(is_error=True)

    async def _update_progress(self, is_error: bool = False):
        """更新进度。completed_tasks 包含成功 + 错误。

        progress 按 (total - error) / total 计算，
        这样错误不影响"有效完成率"的显示。
        """
        async with async_session_factory() as db:
            run = (await db.execute(
                select(EvaluationRun).where(EvaluationRun.id == self.run_id)
            )).scalar_one()
            # 直接从 results 表统计（更准，避免并发竞争）
            from sqlalchemy import func as sa_func
            total_in_db = (await db.execute(
                select(sa_func.count(EvaluationResult.id))
                .where(EvaluationResult.run_id == self.run_id)
            )).scalar_one()
            error_in_db = (await db.execute(
                select(sa_func.count(EvaluationResult.id))
                .where(
                    EvaluationResult.run_id == self.run_id,
                    EvaluationResult.error_message.isnot(None),
                )
            )).scalar_one()

            run.completed_tasks = total_in_db
            total = run.total_tasks or 0
            if total > 0:
                # progress 显示"有效成功率"
                run.progress = int((total - error_in_db) / total * 100)
            else:
                run.progress = 0
            await db.commit()

    async def _mark_run_status(self, status: str, error: str | None = None):
        async with async_session_factory() as db:
            run = (await db.execute(
                select(EvaluationRun).where(EvaluationRun.id == self.run_id)
            )).scalar_one()
            run.status = status
            if error:
                run.summary = {"error": error}
            await db.commit()

    async def _finalize_run(self):
        """汇总 + 写报告。"""
        # 1. 更新 run 状态
        async with async_session_factory() as db:
            run = (await db.execute(
                select(EvaluationRun).where(EvaluationRun.id == self.run_id)
            )).scalar_one()
            results = (await db.execute(
                select(EvaluationResult).where(EvaluationResult.run_id == self.run_id)
            )).scalars().all()

            # 汇总
            summary = self._aggregate(results)
            run.summary = summary

            # 状态：区分 completed / completed_with_errors / failed
            error_count = summary.get("error_count", 0)
            total = run.total_tasks or len(results)
            if total == 0:
                run.status = "completed"
                run.progress = 100
            elif error_count == 0:
                run.status = "completed"
                run.progress = 100
            elif error_count >= total:
                run.status = "failed"
                run.progress = 0
            else:
                run.status = "completed_with_errors"
                run.progress = int((total - error_count) / total * 100)

            run.completed_tasks = len(results)
            run.completed_at = datetime.now(timezone.utc)
            await db.commit()

        # 2. 生成报告文件（永久保留）
        try:
            await ReportGenerator(self.run_id).generate()
        except Exception as e:
            logger.exception(f"生成报告失败: {e}")

    @staticmethod
    def _aggregate(results: list) -> dict:
        """汇总所有 result → summary 指标。

        新指标结构（无 use_ragas 开关，每次都跑）：
        - retrieval.{embedding|retrieval|rerank}.{recall_at_5, precision_at_5, hit_at_5, mrr, ndcg_at_5}
        - generation.{model}.{faithfulness, answer_relevancy, answer_correctness}

        健壮性：safe_avg() 跳过非数字，缺 key 兜底为 0，避免 KeyError。
        """
        # 5 个标准检索指标 + 3 个 LLM 指标（顺序固定）
        STANDARD_RET_KEYS = (
            "recall_at_k", "precision_at_k", "hit_at_k", "mrr", "ndcg_at_k",
        )
        STANDARD_GEN_KEYS = (
            "faithfulness", "answer_relevancy", "answer_correctness",
        )

        def safe_avg(values, default=0.0):
            """对一组值求平均，跳过非数字，缺值兜底为 0。"""
            vals = [v for v in values if isinstance(v, (int, float))]
            return sum(vals) / len(vals) if vals else default

        ret_metrics_grouped = defaultdict(list)
        gen_scores_grouped = defaultdict(list)
        for r in results:
            if r.retrieval_metrics and not r.error_message:
                key = f"{r.embedding_model}|{r.retrieval_strategy}|{r.rerank_model or '-'}"
                ret_metrics_grouped[key].append(r.retrieval_metrics)
            if r.generation_scores and not r.judge_error and not r.error_message:
                gen_scores_grouped[r.generation_model].append(r.generation_scores)

        # retrieval: 硬编码 5 个标准 key（统一口径，避免不同 result 字段不同）
        ret_summary = {
            key: {k: safe_avg([m.get(k) for m in metrics]) for k in STANDARD_RET_KEYS}
            for key, metrics in ret_metrics_grouped.items()
        }
        # generation: 硬编码 3 个标准 key
        gen_summary = {
            key: {k: safe_avg([s.get(k) for s in scores]) for k in STANDARD_GEN_KEYS}
            for key, scores in gen_scores_grouped.items()
        }
        return {
            "retrieval": ret_summary,
            "generation": gen_summary,
            "total_results": len(results),
            "success_count": sum(1 for r in results if not r.error_message),
            "error_count": sum(1 for r in results if r.error_message),
            "error_tasks": [
                {
                    "qa_index": r.qa_index,
                    "embedding_model": r.embedding_model,
                    "retrieval_strategy": r.retrieval_strategy,
                    "rerank_model": r.rerank_model,
                    "generation_model": r.generation_model,
                    "error": r.error_message[:200] if r.error_message else None,
                }
                for r in results if r.error_message
            ],
            "judge_error_count": sum(1 for r in results if r.judge_error),
        }


# 内存中持有运行中的 runner，支持 stop API
_runners: dict[uuid.UUID, EvalRunner] = {}


def get_or_create_runner(run_id: uuid.UUID) -> EvalRunner:
    if run_id not in _runners:
        _runners[run_id] = EvalRunner(run_id)
    return _runners[run_id]


def remove_runner(run_id: uuid.UUID):
    _runners.pop(run_id, None)
