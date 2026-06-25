"""评估系统 Pydantic schemas。"""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


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
    embedding_models: list[str] = Field(default_factory=list)
    retrieval_strategies: list[str] = Field(default_factory=list)
    rerank_models: list[str] = Field(default_factory=list)
    generation_models: list[str] = Field(default_factory=list)
    # 默认参数
    concurrency: int = 4
    # LLM-as-Judge 固定为 mimo-2.5（不允许覆盖）
    # RAGAS 评估开关
    use_ragas: bool = False  # 跑完后再批量评估（慢但更全面）


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
    retrieval_metrics: Optional[dict]
    generation_scores: Optional[dict]
    ragas_scores: Optional[dict]  # 新增：RAGAS 6 个指标
    latency_ms: Optional[int]
    error_message: Optional[str]
    judge_error: bool
    ragas_error: bool  # 新增

    class Config:
        from_attributes = True
