"""评估系统 API 路由。"""
import asyncio
import logging
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import get_current_user, require_admin
from app.db.database import async_session_factory, get_db
from app.models.eval_models import EvaluationDataset, EvaluationResult, EvaluationRun
from app.models.models import User
from app.schemas.eval_schemas import (
    DatasetCreate, DatasetDetailOut, DatasetOut, EvalResultOut,
    EvalRunCreate, EvalRunOut, EvalRunProgress, EVAL_METRIC_KEYS,
)
from app.services.eval import (
    EvalRunner, GoldenDatasetBuilder, ReportGenerator, get_or_create_runner, remove_runner,
)
from app.services.embedding import list_available_models as list_embed_models
from app.services.llm_provider import list_available_models as list_llm_models
from app.services.rerank import list_available_models as list_rerank_models

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/eval", tags=["评估"])


# ==================== 模型列表 ====================

@router.get("/models")
async def get_models(_: User = Depends(get_current_user)):
    """返回所有可用的 embedding / rerank / llm 模型。"""
    return {
        "embeddings": list_embed_models(),
        "reranks": list_rerank_models(),
        "llms": list_llm_models(),
    }


# ==================== 数据集 ====================

@router.post("/datasets", response_model=DatasetDetailOut, status_code=status.HTTP_201_CREATED)
async def create_dataset(
    req: DatasetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """管理员自动生成数据集（默认 20 道题）。"""
    builder = GoldenDatasetBuilder()
    qa_pairs = await builder.generate(kb_id=req.kb_id, n_questions=req.n_questions)

    dataset = EvaluationDataset(
        id=uuid.uuid4(),
        name=req.name,
        kb_id=req.kb_id,
        description=req.description,
        qa_pairs=qa_pairs,
        created_by=current_user.id,
    )
    db.add(dataset)
    await db.commit()
    await db.refresh(dataset)

    return DatasetDetailOut(
        id=dataset.id,
        name=dataset.name,
        kb_id=dataset.kb_id,
        description=dataset.description,
        qa_count=len(qa_pairs),
        qa_pairs=qa_pairs,
        created_at=dataset.created_at,
        created_by=dataset.created_by,
    )


@router.get("/datasets", response_model=List[DatasetOut])
async def list_datasets(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(EvaluationDataset).order_by(desc(EvaluationDataset.created_at))
    )
    rows = result.scalars().all()
    return [
        DatasetOut(
            id=r.id,
            name=r.name,
            kb_id=r.kb_id,
            description=r.description,
            qa_count=len(r.qa_pairs or []),
            created_at=r.created_at,
            created_by=r.created_by,
        )
        for r in rows
    ]


@router.get("/datasets/{dataset_id}", response_model=DatasetDetailOut)
async def get_dataset(
    dataset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(EvaluationDataset).where(EvaluationDataset.id == dataset_id)
    )
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="数据集不存在")
    return DatasetDetailOut(
        id=r.id,
        name=r.name,
        kb_id=r.kb_id,
        description=r.description,
        qa_count=len(r.qa_pairs or []),
        qa_pairs=r.qa_pairs or [],
        created_at=r.created_at,
        created_by=r.created_by,
    )


@router.delete("/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dataset(
    dataset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(
        select(EvaluationDataset).where(EvaluationDataset.id == dataset_id)
    )
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="数据集不存在")
    await db.delete(r)
    await db.commit()


# ==================== 运行 ====================

@router.post("/runs", response_model=EvalRunProgress, status_code=status.HTTP_201_CREATED)
async def create_run(
    req: EvalRunCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """创建评估 run 并启动后台任务。"""
    # 校验数据集
    result = await db.execute(
        select(EvaluationDataset).where(EvaluationDataset.id == req.dataset_id)
    )
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")

    # 创建 run
    # enabled_metrics: None → 全 8 个；列表 → 过滤合法 key
    enabled_metrics = (
        [m for m in (req.enabled_metrics or EVAL_METRIC_KEYS) if m in EVAL_METRIC_KEYS]
        or list(EVAL_METRIC_KEYS)
    )
    # llm_metric_model: None → settings.MIMO_MODEL
    llm_metric_model = (req.llm_metric_model or "").strip() or settings.MIMO_MODEL
    config = {
        "embedding_models": req.embedding_models,
        "retrieval_strategies": req.retrieval_strategies,
        "rerank_models": req.rerank_models,
        "generation_models": req.generation_models,
        "concurrency": req.concurrency,
        "enabled_metrics": enabled_metrics,    # 落库：保证后续报告可还原
        "llm_metric_model": llm_metric_model,  # 落库：保证续跑用同一模型
    }
    run = EvaluationRun(
        id=uuid.uuid4(),
        dataset_id=req.dataset_id,
        name=req.name,
        config=config,
        status="pending",
        created_by=current_user.id,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    # 启动后台任务（asyncio.create_task）
    runner = get_or_create_runner(run.id)
    asyncio.create_task(runner.start())

    return EvalRunProgress(
        id=run.id,
        name=run.name,
        status=run.status,
        progress=run.progress or 0,
        total_tasks=run.total_tasks or 0,
        completed_tasks=run.completed_tasks or 0,
        started_at=run.started_at,
        completed_at=run.completed_at,
        resume_count=run.resume_count or 0,
        config=run.config,
        summary=run.summary,
        report_json_path=run.report_json_path,
        report_md_path=run.report_md_path,
    )


@router.get("/runs", response_model=List[EvalRunOut])
async def list_runs(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(EvaluationRun).order_by(desc(EvaluationRun.created_at))
    )
    rows = result.scalars().all()
    return [
        EvalRunOut(
            id=r.id,
            name=r.name,
            status=r.status,
            progress=r.progress or 0,
            total_tasks=r.total_tasks or 0,
            completed_tasks=r.completed_tasks or 0,
            started_at=r.started_at,
            completed_at=r.completed_at,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/runs/{run_id}", response_model=EvalRunProgress)
async def get_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(EvaluationRun).where(EvaluationRun.id == run_id)
    )
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="评估不存在")
    return EvalRunProgress(
        id=r.id,
        name=r.name,
        status=r.status,
        progress=r.progress or 0,
        total_tasks=r.total_tasks or 0,
        completed_tasks=r.completed_tasks or 0,
        started_at=r.started_at,
        completed_at=r.completed_at,
        resume_count=r.resume_count or 0,
        config=r.config,
        summary=r.summary,
        report_json_path=r.report_json_path,
        report_md_path=r.report_md_path,
    )


@router.get("/runs/{run_id}/progress", response_model=EvalRunProgress)
async def get_progress(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """轻量级进度查询（前端每 2 秒轮询）。"""
    return await get_run(run_id, db, _)


@router.post("/runs/{run_id}/resume")
async def resume_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """续跑（断点续传）：从停止 / 失败处继续。"""
    result = await db.execute(
        select(EvaluationRun).where(EvaluationRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="评估不存在")
    if run.status not in ("stopped", "failed"):
        raise HTTPException(
            status_code=400,
            detail=f"仅 stopped / failed 状态可续跑，当前: {run.status}",
        )

    run.status = "running"
    run.resume_count = (run.resume_count or 0) + 1
    run.last_resumed_at = __import__("datetime").datetime.utcnow()
    await db.commit()

    # 续跑直接用默认 runner（无 use_ragas 开关）
    runner = get_or_create_runner(run_id)
    asyncio.create_task(runner.start())
    return {"resumed": True, "resume_count": run.resume_count}


@router.post("/runs/{run_id}/stop")
async def stop_run(
    run_id: uuid.UUID,
    _: User = Depends(require_admin),
):
    """停止评估（已完成结果保留）。"""
    runner = get_or_create_runner(run_id)
    runner.request_stop()
    return {"stopping": True}


@router.get("/runs/{run_id}/results", response_model=List[EvalResultOut])
async def get_results(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(EvaluationResult)
        .where(EvaluationResult.run_id == run_id)
        .order_by(EvaluationResult.qa_index)
    )
    return [EvalResultOut.model_validate(r) for r in result.scalars().all()]


@router.delete("/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """删除 run（DB + 报告文件）。"""
    result = await db.execute(
        select(EvaluationRun).where(EvaluationRun.id == run_id)
    )
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="评估不存在")

    # 删除报告文件
    import os
    if r.report_json_path and os.path.exists(r.report_json_path):
        os.remove(r.report_json_path)
    if r.report_md_path and os.path.exists(r.report_md_path):
        os.remove(r.report_md_path)

    await db.delete(r)
    await db.commit()
    remove_runner(run_id)
