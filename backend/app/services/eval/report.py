"""评估报告生成器。

文件名规则：
  eval_{run_name_safe}_{YYYYMMDD_HHMMSS}_{run_id_short}.{json|md}

历史永久保留，不自动清理。
"""
import json
import logging
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.database import async_session_factory
from app.models.eval_models import EvaluationResult, EvaluationRun

logger = logging.getLogger(__name__)


def sanitize_filename(name: str) -> str:
    """清洗 run.name → 文件名安全字符串。"""
    safe = re.sub(r'[\\/:\*\?"<>\|\r\n\t]', '', name)
    safe = safe.replace(" ", "_")
    return safe[:50] or "unnamed"


def build_filename(run: EvaluationRun) -> str:
    """生成报告文件名前缀。"""
    safe_name = sanitize_filename(run.name)
    ts = (run.started_at or run.created_at).strftime("%Y%m%d_%H%M%S")
    id8 = str(run.id).replace("-", "")[:8]
    return f"eval_{safe_name}_{ts}_{id8}"


class ReportGenerator:
    def __init__(self, run_id: uuid.UUID):
        self.run_id = run_id
        self._dir = Path(settings.EVAL_REPORT_DIR)
        self._dir.mkdir(parents=True, exist_ok=True)

    async def generate(self) -> tuple[str, str]:
        """生成 JSON + Markdown 报告，返回 (json_path, md_path)。"""
        async with async_session_factory() as db:
            run = (await db.execute(
                select(EvaluationRun).where(EvaluationRun.id == self.run_id)
            )).scalar_one()
            results = (await db.execute(
                select(EvaluationResult).where(EvaluationResult.run_id == self.run_id)
            )).scalars().all()

        prefix = build_filename(run)
        json_path = self._dir / f"{prefix}.json"
        md_path = self._dir / f"{prefix}.md"

        # JSON
        json_data = {
            "run_id": str(self.run_id),
            "name": run.name,
            "status": run.status,
            "config": run.config,
            "summary": run.summary,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "results": [self._result_to_dict(r) for r in results],
        }
        json_path.write_text(
            json.dumps(json_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Markdown
        md_path.write_text(
            self._render_markdown(run, results),
            encoding="utf-8",
        )

        # 写回路径
        async with async_session_factory() as db:
            r = (await db.execute(
                select(EvaluationRun).where(EvaluationRun.id == self.run_id)
            )).scalar_one()
            r.report_json_path = str(json_path)
            r.report_md_path = str(md_path)
            await db.commit()

        logger.info(f"报告已生成: {json_path.name}, {md_path.name}")
        return str(json_path), str(md_path)

    @staticmethod
    def _result_to_dict(r: EvaluationResult) -> dict:
        return {
            "qa_index": r.qa_index,
            "question": r.question,
            "ground_truth": r.ground_truth,
            "embedding_model": r.embedding_model,
            "retrieval_strategy": r.retrieval_strategy,
            "rerank_model": r.rerank_model,
            "generation_model": r.generation_model,
            "retrieved_chunks": r.retrieved_chunks,
            "generated_answer": r.generated_answer,
            "retrieval_metrics": r.retrieval_metrics,
            "generation_scores": r.generation_scores,
            "latency_ms": r.latency_ms,
            "error_message": r.error_message,
            "judge_error": r.judge_error,
        }

    def _render_markdown(self, run: EvaluationRun, results: List[EvaluationResult]) -> str:
        """渲染 Markdown 报告。"""
        lines = []
        lines.append(f"# 评估报告 - {run.name}")
        lines.append("")
        lines.append(f"- **Run ID**: `{self.run_id}`")
        lines.append(f"- **状态**: {run.status}")
        lines.append(f"- **进度**: {run.progress}%")
        lines.append(f"- **已完成任务**: {run.completed_tasks} / {run.total_tasks}")
        if run.started_at:
            lines.append(f"- **开始时间**: {run.started_at.strftime('%Y-%m-%d %H:%M:%S')}")
        if run.completed_at:
            lines.append(f"- **完成时间**: {run.completed_at.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"- **续跑次数**: {run.resume_count}")
        lines.append("")

        def safe_avg(values, default=0.0):
            """过滤非数字后求平均；全 None 兜底为 0。"""
            vals = [v for v in values if isinstance(v, (int, float))]
            return sum(vals) / len(vals) if vals else default

        # 配置
        cfg = run.config or {}
        lines.append("## 配置")
        lines.append(f"- **Embedding**: {', '.join(cfg.get('embedding_models', []))}")
        lines.append(f"- **Retrieval**: {', '.join(cfg.get('retrieval_strategies', []))}")
        if cfg.get('rerank_models'):
            lines.append(f"- **Rerank**: {', '.join(cfg.get('rerank_models', []))}")
        lines.append(f"- **Generation**: {', '.join(cfg.get('generation_models', []))}")
        lines.append(f"- **LLM 评估模型**: {settings.MIMO_LITE_MODEL}（可在 .env 改 MIMO_LITE_MODEL）")
        lines.append(f"- **评估指标**: 5 检索 + 3 LLM（共 8 个，每次都默认跑，无开关）")
        lines.append("")

        # 检索指标（5 列）
        ret_results = [r for r in results if r.retrieval_metrics]
        if ret_results:
            lines.append("## 检索指标汇总（5 个标准指标 · K=5）")
            lines.append("")
            lines.append(
                "| Embedding | Retrieval | Rerank | "
                "Recall@5 | Precision@5 | Hit@5 | MRR | NDCG@5 |"
            )
            lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
            # 按 (embedding, retrieval, rerank) 分组
            grouped = defaultdict(list)
            for r in ret_results:
                key = (r.embedding_model, r.retrieval_strategy, r.rerank_model or "-")
                grouped[key].append(r.retrieval_metrics)
            for (emb, ret, rm), metrics_list in sorted(grouped.items()):
                # 5 个标准 key，safe_avg 避免缺字段出错
                base_keys = (
                    "recall_at_k", "precision_at_k",
                    "hit_at_k", "mrr", "ndcg_at_k",
                )
                avg = {k: safe_avg([m.get(k) for m in metrics_list]) for k in base_keys}
                lines.append(
                    f"| {emb} | {ret} | {rm} | "
                    f"{avg.get('recall_at_k', 0):.3f} | "
                    f"{avg.get('precision_at_k', 0):.3f} | "
                    f"{avg.get('hit_at_k', 0):.3f} | "
                    f"{avg.get('mrr', 0):.3f} | "
                    f"{avg.get('ndcg_at_k', 0):.3f} |"
                )
            lines.append("")

        # 生成质量（3 个 LLM 指标 · 新名字）
        gen_results = [r for r in results if r.generation_scores and not r.judge_error]
        if gen_results:
            lines.append("## 生成质量（3 个 LLM 指标 · 基于 LangChain）")
            lines.append("")
            lines.append(
                "| Generation | Faithfulness / Groundedness | "
                "Answer Relevancy | Answer Correctness |"
            )
            lines.append("| --- | --- | --- | --- |")
            grouped = defaultdict(list)
            for r in gen_results:
                grouped[r.generation_model].append(r.generation_scores)
            STANDARD_GEN_KEYS = ("faithfulness", "answer_relevancy", "answer_correctness")
            for gm, scores_list in sorted(grouped.items()):
                avg = {k: safe_avg([s.get(k) for s in scores_list]) for k in STANDARD_GEN_KEYS}
                lines.append(
                    f"| {gm} | "
                    f"{avg.get('faithfulness', 0):.3f} | "
                    f"{avg.get('answer_relevancy', 0):.3f} | "
                    f"{avg.get('answer_correctness', 0):.3f} |"
                )
            lines.append("")

            # 总体均值（来自 summary）
            summary = run.summary or {}
            gen_overall = summary.get("generation", {})
            if gen_overall:
                lines.append("### 生成指标总体均值")
                for gm_key, scores_dict in gen_overall.items():
                    if isinstance(scores_dict, dict):
                        parts = ", ".join(
                            f"{k}={v:.3f}" for k, v in scores_dict.items()
                            if isinstance(v, (int, float))
                        )
                        if parts:
                            lines.append(f"- **{gm_key}**: {parts}")
                lines.append("")

        # 错误汇总
        errors = [r for r in results if r.error_message]
        judge_errors = [r for r in results if r.judge_error]
        if errors or judge_errors:
            lines.append("## ⚠️ 错误汇总")
            if errors:
                lines.append(f"- 主任务错误: {len(errors)} 个")
            if judge_errors:
                lines.append(f"- LLM 指标评估错误: {len(judge_errors)} 个")
            lines.append("")

        return "\n".join(lines)
