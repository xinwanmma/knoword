"""评估系统数据模型。

- EvaluationDataset: 数据集
- EvaluationRun:     一次评估运行
- EvaluationResult:  单个 task 的结果
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.database import Base


class EvaluationDataset(Base):
    __tablename__ = "evaluation_datasets"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    kb_id = Column(Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"))
    qa_pairs = Column(JSONB, nullable=False)  # [{question, ground_truth, source_chunk_ids, source_doc_ids}, ...]
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    created_by = Column(UUID, ForeignKey("users.id"))


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    dataset_id = Column(UUID, ForeignKey("evaluation_datasets.id", ondelete="CASCADE"))
    name = Column(String(200), nullable=False)
    # config 包含：embedding_models, retrieval_strategies, rerank_models, generation_models
    config = Column(JSONB, nullable=False)
    # status: pending / running / stopped / completed / failed
    status = Column(String(20), default="pending")
    progress = Column(Integer, default=0)  # 0-100
    total_tasks = Column(Integer, default=0)
    completed_tasks = Column(Integer, default=0)
    summary = Column(JSONB)  # 汇总指标
    # 断点续传
    resume_count = Column(Integer, default=0)
    last_resumed_at = Column(DateTime(timezone=True))
    # 报告路径
    report_json_path = Column(String(500))
    report_md_path = Column(String(500))
    # 时间
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_by = Column(UUID, ForeignKey("users.id"))


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID, ForeignKey("evaluation_runs.id", ondelete="CASCADE"))
    qa_index = Column(Integer, nullable=False)
    question = Column(Text)
    ground_truth = Column(Text)
    embedding_model = Column(String(100), nullable=False)
    retrieval_strategy = Column(String(50), nullable=False)
    rerank_model = Column(String(100))
    generation_model = Column(String(100), nullable=False)
    retrieved_chunks = Column(JSONB)
    generated_answer = Column(Text)
    retrieval_metrics = Column(JSONB)  # {hit_at_5, mrr, ndcg_at_5, recall_at_5}
    generation_scores = Column(JSONB)  # LLM-as-Judge: {faithfulness, relevance, completeness}
    ragas_scores = Column(JSONB)  # RAGAS: {faithfulness, answer_relevancy, context_relevancy, context_recall, context_precision, answer_correctness}
    latency_ms = Column(Integer)
    # 错误处理
    error_message = Column(Text)
    judge_error = Column(Boolean, default=False)
    ragas_error = Column(Boolean, default=False)  # RAGAS 评估失败标记
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint(
            "run_id", "qa_index", "embedding_model",
            "retrieval_strategy", "rerank_model", "generation_model",
            name="uq_eval_result",
        ),
    )
