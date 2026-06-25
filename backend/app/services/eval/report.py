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
            "retrieval_metrics": r.retrieval_metrics,
            "generation_scores": r.generation_scores,
            "ragas_scores": r.ragas_scores,
            "latency_ms": r.latency_ms,
            "error_message": r.error_message,
            "judge_error": r.judge_error,
            "ragas_error": r.ragas_error,
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

        # 配置
        cfg = run.config or {}
        lines.append("## 配置")
        lines.append(f"- **Embedding**: {', '.join(cfg.get('embedding_models', []))}")
        lines.append(f"- **Retrieval**: {', '.join(cfg.get('retrieval_strategies', []))}")
        if cfg.get('rerank_models'):
            lines.append(f"- **Rerank**: {', '.join(cfg.get('rerank_models', []))}")
        lines.append(f"- **Generation**: {', '.join(cfg.get('generation_models', []))}")
        lines.append(f"- **LLM-as-Judge**: mimo-v2.5（固定）")
        lines.append(f"- **RAGAS**: {'✅ 启用' if cfg.get('use_ragas') else '❌ 未启用'}")
        lines.append("")

        # 检索指标
        ret_results = [r for r in results if r.retrieval_metrics]
        if ret_results:
            lines.append("## 检索指标汇总")
            lines.append("")
            lines.append("| Embedding | Retrieval | Rerank | Hit@5 | MRR | NDCG@5 | Recall@5 |")
            lines.append("| --- | --- | --- | --- | --- | --- | --- |")
            # 按 (embedding, retrieval, rerank) 分组
            grouped = defaultdict(list)
            for r in ret_results:
                key = (r.embedding_model, r.retrieval_strategy, r.rerank_model or "-")
                grouped[key].append(r.retrieval_metrics)
            for (emb, ret, rm), metrics_list in sorted(grouped.items()):
                avg = {k: sum(m[k] for m in metrics_list) / len(metrics_list)
                       for k in metrics_list[0]}
                lines.append(
                    f"| {emb} | {ret} | {rm} | {avg.get('hit_at_5', 0):.3f} | "
                    f"{avg.get('mrr', 0):.3f} | {avg.get('ndcg_at_5', 0):.3f} | "
                    f"{avg.get('recall_at_5', 0):.3f} |"
                )
            lines.append("")

        # 生成质量（LLM-as-Judge）
        gen_results = [r for r in results if r.generation_scores and not r.judge_error]
        if gen_results:
            lines.append("## 生成质量（LLM-as-Judge · mimo-v2.5）")
            lines.append("")
            lines.append("| Generation | Faithfulness | Relevance | Completeness |")
            lines.append("| --- | --- | --- | --- |")
            grouped = defaultdict(list)
            for r in gen_results:
                grouped[r.generation_model].append(r.generation_scores)
            for gm, scores_list in sorted(grouped.items()):
                avg = {
                    k: sum(s[k] for s in scores_list) / len(scores_list)
                    for k in scores_list[0] if k in ("faithfulness", "relevance", "completeness")
                }
                lines.append(
                    f"| {gm} | {avg.get('faithfulness', 0):.2f} | "
                    f"{avg.get('relevance', 0):.2f} | {avg.get('completeness', 0):.2f} |"
                )
            lines.append("")

        # RAGAS 指标
        ragas_results = [r for r in results if r.ragas_scores and not r.ragas_error]
        if ragas_results:
            lines.append("## 生成质量（RAGAS · 更全面）")
            lines.append("")
            ragas_metric_names = [
                "faithfulness", "answer_relevancy", "context_relevancy",
                "context_recall", "context_precision", "answer_correctness",
            ]
            header = "| Generation | " + " | ".join(ragas_metric_names) + " |"
            sep = "| --- | " + " | ".join(["---"] * len(ragas_metric_names)) + " |"
            lines.append(header)
            lines.append(sep)
            grouped = defaultdict(list)
            for r in ragas_results:
                grouped[r.generation_model].append(r.ragas_scores)
            for gm, scores_list in sorted(grouped.items()):
                row = [gm]
                for m in ragas_metric_names:
                    vals = [s.get(m) for s in scores_list if s.get(m) is not None]
                    if vals:
                        row.append(f"{sum(vals) / len(vals):.3f}")
                    else:
                        row.append("-")
                lines.append("| " + " | ".join(row) + " |")
            lines.append("")

            # RAGAS 整体汇总（来自 summary）
            summary = run.summary or {}
            ragas_overall = summary.get("ragas", {})
            if ragas_overall and isinstance(ragas_overall, dict):
                lines.append("### RAGAS 总体均值")
                for m, v in ragas_overall.items():
                    if m != "error" and isinstance(v, (int, float)):
                        lines.append(f"- {m}: {v:.4f}")
                if ragas_overall.get("error"):
                    lines.append(f"\n⚠️ RAGAS 错误: {ragas_overall['error']}")
                lines.append("")

        # 错误汇总
        errors = [r for r in results if r.error_message]
        ragas_errors = [r for r in results if r.ragas_error]
        if errors or ragas_errors:
            lines.append("## ⚠️ 错误汇总")
            if errors:
                lines.append(f"- 主任务错误: {len(errors)} 个")
            if ragas_errors:
                lines.append(f"- RAGAS 评估错误: {len(ragas_errors)} 个")
            lines.append("")

        return "\n".join(lines)
