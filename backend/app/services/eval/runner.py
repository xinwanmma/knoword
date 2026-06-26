"""评估运行器 — 核心执行引擎。

关键设计：
1. **细粒度持久化**：每个 task 一完成就 commit，绝不在内存中累积
2. **断点续传**：启动时查询已完成 task，只跑未完成的
3. **并行执行**：asyncio.Semaphore 控制并发（默认 4）
4. **可取消**：用户停止时优雅退出，已完成结果全部保留
5. **独立 session**：每个 task 独立 session，避免连接池耗尽
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
from app.services.embedding import get_embedding_provider
from app.services.eval.judge import LLMJudge
from app.services.eval.metrics import compute_retrieval_metrics
from app.services.eval.report import ReportGenerator
from app.services.llm_provider import get_llm_provider
from app.services.rerank import get_rerank_provider
from app.services.retrieval import get_retrieval_strategy

logger = logging.getLogger(__name__)


class EvalRunner:
    """评估运行器。"""

    def __init__(self, run_id: uuid.UUID, use_ragas: bool = False):
        self.run_id = run_id
        self._stop_flag = asyncio.Event()
        self._semaphore = asyncio.Semaphore(settings.DEFAULT_EVAL_CONCURRENCY)
        self._judge = LLMJudge()
        self._use_ragas = use_ragas

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

        # 2. 展开 task
        all_tasks = self._expand_tasks(dataset.qa_pairs, run.config)
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

    def _expand_tasks(self, qa_pairs: list, config: dict) -> list[dict]:
        """展开笛卡尔积：每个 (qa × embedding × retrieval × rerank × generation) 一个 task。"""
        embed_models = config.get("embedding_models", [])
        retrievals = config.get("retrieval_strategies", [])
        generations = config.get("generation_models", [])
        rerank_models = config.get("rerank_models", [])

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
        """执行单个 task：检索 → 生成 → Judge。"""
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

        # 3. Judge（固定 mimo-v2.5）
        scores = await self._judge.score(
            question=task["question"],
            ground_truth=task["ground_truth"],
            answer=answer,
        )

        # 4. 检索指标
        ret_metrics = compute_retrieval_metrics(
            retrieved_ids, task.get("source_chunk_ids", []), k=5
        )

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
            "generation_scores": scores,
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

    async def _update_progress(self):
        async with async_session_factory() as db:
            run = (await db.execute(
                select(EvaluationRun).where(EvaluationRun.id == self.run_id)
            )).scalar_one()
            run.completed_tasks = (run.completed_tasks or 0) + 1
            run.progress = int(
                run.completed_tasks / run.total_tasks * 100
            ) if run.total_tasks else 0
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
            summary["use_ragas"] = self._use_ragas
            run.summary = summary
            run.status = "completed"
            run.progress = 100
            run.completed_at = datetime.now(timezone.utc)
            await db.commit()

        # 2. 如果启用 RAGAS，批量回填（异步，不阻塞报告生成）
        if self._use_ragas:
            try:
                from app.services.eval.ragas_eval import RagasEvaluator
                evaluator = RagasEvaluator()
                ragas_summary = await evaluator.score_run(self.run_id)
                # 把 RAGAS 汇总写回 run.summary
                async with async_session_factory() as db:
                    run = (await db.execute(
                        select(EvaluationRun).where(EvaluationRun.id == self.run_id)
                    )).scalar_one()
                    if run.summary is None:
                        run.summary = {}
                    run.summary["ragas"] = ragas_summary
                    await db.commit()
            except Exception as e:
                logger.exception(f"RAGAS 回填失败: {e}")

        # 3. 生成报告文件（永久保留）
        try:
            await ReportGenerator(self.run_id).generate()
        except Exception as e:
            logger.exception(f"生成报告失败: {e}")

    @staticmethod
    def _aggregate(results: list) -> dict:
        """汇总所有 result → summary 指标。

        健壮性：使用 safe_avg + dict.get()，避免个别 result 字段缺失导致 KeyError。
        """
        STANDARD_GEN_KEYS = ("faithfulness", "relevance", "completeness")

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

        # retrieval: 以该 group 第一个 result 的 keys 为基准（兼容老格式）
        ret_summary = {
            key: {k: safe_avg([m.get(k) for m in metrics]) for k in (metrics[0] or {})}
            for key, metrics in ret_metrics_grouped.items()
        }
        # generation: 硬编码标准 3 个 key，避免依赖 scores[0]
        gen_summary = {
            key: {k: safe_avg([s.get(k) for s in scores]) for k in STANDARD_GEN_KEYS}
            for key, scores in gen_scores_grouped.items()
        }
        return {
            "retrieval": ret_summary,
            "generation": gen_summary,
            "total_results": len(results),
            "error_count": sum(1 for r in results if r.error_message),
            "judge_error_count": sum(1 for r in results if r.judge_error),
        }


# 内存中持有运行中的 runner，支持 stop API
_runners: dict[uuid.UUID, EvalRunner] = {}


def get_or_create_runner(run_id: uuid.UUID, use_ragas: bool = False) -> EvalRunner:
    if run_id not in _runners:
        _runners[run_id] = EvalRunner(run_id, use_ragas=use_ragas)
    return _runners[run_id]


def remove_runner(run_id: uuid.UUID):
    _runners.pop(run_id, None)
