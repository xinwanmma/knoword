"""enlarge evaluation_runs.status to 30 chars

修复 bug：status 字段 String(20) 太短，写入 "completed_with_errors"（22 字符）
时触发 PostgreSQL StringDataRightTruncationError，导致 _finalize_run 失败，
run 状态卡在 failed、报告无法生成。

改为 String(30)，为后续 status 枚举预留余量。
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = 'a8b9c0d1e2f3'
down_revision: Union[str, None] = '9f8e7d6c5b4a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'evaluation_runs',
        'status',
        existing_type=sa.String(length=20),
        type_=sa.String(length=30),
        existing_nullable=True,
        postgresql_using='status::VARCHAR(30)',
    )


def downgrade() -> None:
    op.alter_column(
        'evaluation_runs',
        'status',
        existing_type=sa.String(length=30),
        type_=sa.String(length=20),
        existing_nullable=True,
        postgresql_using='status::VARCHAR(20)',
    )
