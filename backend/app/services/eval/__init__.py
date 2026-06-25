"""评估服务入口。"""
from app.services.eval.dataset_builder import GoldenDatasetBuilder
from app.services.eval.judge import LLMJudge
from app.services.eval.metrics import compute_retrieval_metrics
from app.services.eval.report import ReportGenerator
from app.services.eval.runner import EvalRunner, get_or_create_runner, remove_runner

__all__ = [
    "GoldenDatasetBuilder",
    "LLMJudge",
    "compute_retrieval_metrics",
    "ReportGenerator",
    "EvalRunner",
    "get_or_create_runner",
    "remove_runner",
]
