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
from typing import List, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.database import async_session_factory
from app.models.eval_models import EvaluationResult, EvaluationRun
from app.schemas.eval_schemas import EVAL_METRIC_KEYS, EVAL_METRIC_LABELS

logger = logging.getLogger(__name__)


# 内部小工具：把 enabled list 转 set
def _enabled_set(value) -> Set[str]:
    if not value:
        return set(EVAL_METRIC_KEYS)
    return {m for m in value if m in EVAL_METRIC_KEYS}


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
        enabled = _enabled_set(cfg.get("enabled_metrics"))
        llm_model = cfg.get("llm_metric_model") or settings.MIMO_MODEL
        # embedding_model 兼容旧字段（embedding_models 复数是 A 方案遗留，已废弃）
        embedding = cfg.get("embedding_model") or (cfg.get("embedding_models") or [None])[0] or "未指定"
        lines.append("## 配置")
        lines.append(f"- **Embedding**: {embedding}")
        lines.append(f"- **Retrieval**: {', '.join(cfg.get('retrieval_strategies', []))}")
        if cfg.get('rerank_models'):
            lines.append(f"- **Rerank**: {', '.join(cfg.get('rerank_models', []))}")
        lines.append(f"- **Generation**: {', '.join(cfg.get('generation_models', []))}")
        lines.append(f"- **LLM 评估模型**: {llm_model}")
        # 启用的指标（带中文 label）
        enabled_labels = [
            EVAL_METRIC_LABELS.get(k, k) for k in EVAL_METRIC_KEYS if k in enabled
        ]
        lines.append(
            f"- **启用的指标**（{len(enabled)}/{len(EVAL_METRIC_KEYS)}）: "
            f"{', '.join(enabled_labels) or '无'}"
        )
        # 关闭的指标
        disabled_keys = [k for k in EVAL_METRIC_KEYS if k not in enabled]
        if disabled_keys:
            disabled_labels = [EVAL_METRIC_LABELS.get(k, k) for k in disabled_keys]
            lines.append(f"- **关闭的指标**: {', '.join(disabled_labels)}")
        lines.append("")

        # 检索指标（按 enabled 决定列）
        ret_results = [r for r in results if r.retrieval_metrics]
        if ret_results and enabled & {
            "recall_at_k", "precision_at_k", "hit_at_k", "mrr", "ndcg_at_k",
        }:
            # 是否多个 generation 模型（决定表格是否要 Generation 列）
            gens = sorted({r.generation_model for r in ret_results if r.generation_model})
            multi_gen = len(gens) > 1

            # K 从 run.config 读，缺省 10（之前是硬编码 5）
            K_VAL = (run.config or {}).get("eval_top_k") or 10
            lines.append(f"## 检索指标汇总（K={K_VAL}）")
            lines.append("")
            ret_keys = [
                k for k in ("recall_at_k", "precision_at_k", "hit_at_k", "mrr", "ndcg_at_k")
                if k in enabled
            ]
            header_metrics = " | ".join(EVAL_METRIC_LABELS[k] for k in ret_keys)
            # 表格：去掉冗余的 Embedding 列（移到 sub-header），加 Generation 列
            if multi_gen:
                lines.append(f"| Retrieval | Rerank | Generation | {header_metrics} |")
                lines.append("| --- | --- | --- |" + " --- |" * len(ret_keys))
            else:
                lines.append(f"| Retrieval | Rerank | {header_metrics} |")
                lines.append("| --- | --- |" + " --- |" * len(ret_keys))
            # 按 (retrieval, rerank, generation) 分组（embedding 已在 sub-header）
            grouped = defaultdict(list)
            for r in ret_results:
                key = (r.retrieval_strategy, r.rerank_model or "-", r.generation_model or "-")
                grouped[key].append(r.retrieval_metrics)
            for (ret, rm, gen), metrics_list in sorted(grouped.items()):
                avg = {k: safe_avg([m.get(k) for m in metrics_list]) for k in ret_keys}
                vals = " | ".join(f"{avg.get(k, 0):.3f}" for k in ret_keys)
                if multi_gen:
                    lines.append(f"| {ret} | {rm} | {gen} | {vals} |")
                else:
                    lines.append(f"| {ret} | {rm} | {vals} |")
            lines.append("")

        # 生成质量（3 个 LLM 指标 · 按 enabled 过滤）
        gen_results = [r for r in results if r.generation_scores and not r.judge_error]
        gen_keys = [k for k in ("faithfulness", "answer_relevancy", "answer_correctness") if k in enabled]
        if gen_results and gen_keys:
            # 是否多 retrieval 策略（决定是否加 Retrieval 列）
            ret_strats = sorted({r.retrieval_strategy for r in gen_results if r.retrieval_strategy})
            multi_ret = len(ret_strats) > 1

            lines.append("## 生成质量（LLM 指标 · 基于 LangChain）")
            lines.append("")
            header_gen = " | ".join(EVAL_METRIC_LABELS[k] for k in gen_keys)
            if multi_ret:
                lines.append(f"| Generation | Retrieval | {header_gen} |")
                lines.append("| --- | --- |" + " --- |" * len(gen_keys))
            else:
                lines.append(f"| Generation | {header_gen} |")
                lines.append("| --- |" + " --- |" * len(gen_keys))
            # 按 (generation, retrieval) 分组
            grouped = defaultdict(list)
            for r in gen_results:
                key = (r.generation_model, r.retrieval_strategy or "-")
                grouped[key].append(r.generation_scores)
            for (gm, ret), scores_list in sorted(grouped.items()):
                avg = {k: safe_avg([s.get(k) for s in scores_list]) for k in gen_keys}
                vals = " | ".join(f"{avg.get(k, 0):.3f}" for k in gen_keys)
                if multi_ret:
                    lines.append(f"| {gm} | {ret} | {vals} |")
                else:
                    lines.append(f"| {gm} | {vals} |")
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

        # P3 out-of-scope 表现（如果 dataset 包含 OOS 题）
        oos_results = [r for r in results if r.is_out_of_scope]
        if oos_results:
            lines.append("## Out-of-Scope 表现（KB 中无答案的题）")
            lines.append(f"共 {len(oos_results)} 道 OOS 题。预期：Recall@K=0，Faithfulness / Answer Relevancy 应该低。")
            lines.append("")
            lines.append("| Generation | Retrieval | Faithfulness | Answer Relevancy | Answer Correctness |")
            lines.append("|---|---|---|---|---|")
            oos_grouped = {}
            for r in oos_results:
                key = (r.generation_model or "-", r.retrieval_strategy or "-")
                oos_grouped.setdefault(key, []).append(r.generation_scores or {})
            for (gm, ret), scores_list in sorted(oos_grouped.items()):
                f_vals = [s.get("faithfulness") for s in scores_list if s.get("faithfulness") is not None]
                r_vals = [s.get("answer_relevancy") for s in scores_list if s.get("answer_relevancy") is not None]
                c_vals = [s.get("answer_correctness") for s in scores_list if s.get("answer_correctness") is not None]
                f_avg = sum(f_vals) / len(f_vals) if f_vals else 0.0
                r_avg = sum(r_vals) / len(r_vals) if r_vals else 0.0
                c_avg = sum(c_vals) / len(c_vals) if c_vals else 0.0
                lines.append(f"| {gm} | {ret} | {f_avg:.3f} | {r_avg:.3f} | {c_avg:.3f} |")
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
