"""dedupe eval_results + null-safe unique constraint

修复 2 个 bug：

1. **重复行**：`upsert` 用了 UniqueConstraint(run_id, qa_index, embedding_model,
   retrieval_strategy, rerank_model, generation_model)，但 PostgreSQL 默认
   把 NULL 视为不同，导致 vector / hybrid 策略（rerank_model=NULL）重跑时
   不触发 upsert，**创建了 35 个新行**。

2. **续跑漏跑 99 个 mimo 402 任务**：`_get_completed_task_keys()` 只过滤
   `judge_error=False`，没过滤 `retrieved_chunks IS NULL` 的行，
   导致 99 个主任务失败的 task 永远被当成"已完成"。

本次迁移：
1. 删除 (run_id, qa_index, embedding_model, retrieval_strategy, rerank_model, generation_model)
   上的重复行，保留 created_at 最新那条
2. 删除旧 UniqueConstraint
3. 新建 UniqueConstraint 使用 NULLS NOT DISTINCT，让 rerank_model=NULL 的行也能正确 upsert
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = 'b9c0d1e2f3a4'
down_revision: Union[str, None] = 'a8b9c0d1e2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 删除重复行：保留 created_at 最新那条
    #    用 DELETE ... WHERE id IN (SELECT id FROM ... WHERE row_number > 1)
    op.execute("""
        DELETE FROM evaluation_results
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY run_id, qa_index, embedding_model,
                                        retrieval_strategy, rerank_model, generation_model
                           ORDER BY created_at DESC
                       ) AS rn
                FROM evaluation_results
            ) t
            WHERE rn > 1
        )
    """)

    # 2. 删除旧 UniqueConstraint
    op.drop_constraint("uq_eval_result", "evaluation_results", type_="unique")

    # 3. 新建 NULLS NOT DISTINCT 的 UniqueConstraint
    op.create_unique_constraint(
        "uq_eval_result",
        "evaluation_results",
        ["run_id", "qa_index", "embedding_model",
         "retrieval_strategy", "rerank_model", "generation_model"],
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    # 1. 删 NULLS NOT DISTINCT 的 UniqueConstraint
    op.drop_constraint("uq_eval_result", "evaluation_results", type_="unique")

    # 2. 恢复旧 UniqueConstraint（接受 NULL 视为不同 → 倒退 bug，但保留 schema 一致性）
    op.create_unique_constraint(
        "uq_eval_result",
        "evaluation_results",
        ["run_id", "qa_index", "embedding_model",
         "retrieval_strategy", "rerank_model", "generation_model"],
    )
