"""评估系统 Pydantic schemas。"""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ==================== 评估指标 ====================

# 5 个检索指标（纯算法）+ 3 个 LLM 指标（基于 LangChain）
EVAL_METRIC_KEYS: list[str] = [
    # 检索
    "recall_at_k", "precision_at_k", "hit_at_k", "mrr", "ndcg_at_k",
    # LLM
    "faithfulness", "answer_relevancy", "answer_correctness",
]

EVAL_METRIC_LABELS: dict[str, str] = {
    "recall_at_k": "Recall@K",
    "precision_at_k": "Precision@K",
    "hit_at_k": "Hit@K",
    "mrr": "MRR",
    "ndcg_at_k": "NDCG@K",
    "faithfulness": "Faithfulness / Groundedness",
    "answer_relevancy": "Answer Relevancy",
    "answer_correctness": "Answer Correctness",
}


# ==================== 数据集 ====================

class QAPair(BaseModel):
    question: str
    ground_truth: str
    source_chunk_ids: list[str] = []
    source_doc_ids: list[int] = []


class DatasetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    kb_id: int
    description: Optional[str] = None
    n_questions: int = 20  # 默认 20（来自 settings.DEFAULT_EVAL_QA_COUNT）


class DatasetOut(BaseModel):
    id: uuid.UUID
    name: str
    kb_id: int
    description: Optional[str]
    qa_count: int
    created_at: datetime
    created_by: uuid.UUID

    class Config:
        from_attributes = True


class DatasetDetailOut(DatasetOut):
    qa_pairs: list[dict]


# ==================== 评估运行 ====================

class EvalRunCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    dataset_id: uuid.UUID
    # 评估要检索的 KB 列表（多选 = 多 embedding 模型对比）
    # 同一文档用不同 embedding 模型构建成不同 KB → 选多个 KB 即可对比不同 embedding 的检索质量
    # 注意：embedding 模型是 KB 的物理属性，不能跨 KB 切换
    kb_ids: list[int] = Field(default_factory=list)
    # [已废弃] 保留向后兼容：从前端来的 embedding_models 字段会映射成 kb_ids（按 KB 名字匹配）
    # 实际跑评估时按 KB 绑定的 embedding model，UI 不再让选
    embedding_models: Optional[list[str]] = None
    retrieval_strategies: list[str] = Field(default_factory=list)
    rerank_models: list[str] = Field(default_factory=list)
    generation_models: list[str] = Field(default_factory=list)
    # 默认参数
    concurrency: int = 4
    # 启用的评估指标（None = 全开 8 个）
    # 合法值见 EVAL_METRIC_KEYS
    enabled_metrics: Optional[list[str]] = None
    # LLM 评估用的 judge 模型（None = settings.MIMO_MODEL）
    llm_metric_model: Optional[str] = None


class EvalRunProgress(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    progress: int
    total_tasks: int
    completed_tasks: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    resume_count: int
    config: dict
    summary: Optional[dict] = None
    report_json_path: Optional[str] = None
    report_md_path: Optional[str] = None


class EvalRunOut(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    progress: int
    total_tasks: int
    completed_tasks: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class EvalResultOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    qa_index: int
    question: str
    ground_truth: Optional[str]
    embedding_model: str
    retrieval_strategy: str
    rerank_model: Optional[str]
    generation_model: str
    retrieved_chunks: Optional[list[dict]]
    generated_answer: Optional[str]
    retrieval_metrics: Optional[dict]  # 5 检索指标（recall_at_k/precision_at_k/hit_at_k/mrr/ndcg_at_k）
    generation_scores: Optional[dict]  # 3 LLM 指标（faithfulness/answer_relevancy/answer_correctness）
    latency_ms: Optional[int]
    error_message: Optional[str]
    judge_error: bool

    class Config:
        from_attributes = True
