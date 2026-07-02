"""add is_multihop and is_out_of_scope to evaluation_results

P2/P3 新增字段：
- is_multihop: 该 task 是否是 multi-hop 题（必须综合 2+ chunk 才能答）
- is_out_of_scope: 该 task 是否是 out-of-scope 题（KB 中无答案）

default=False，向后兼容老 dataset。
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = '9f8e7d6c5b4a'
down_revision: Union[str, None] = '0b2d7d870f87'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'evaluation_results',
        sa.Column('is_multihop', sa.Boolean(), nullable=True, server_default=sa.text('false')),
    )
    op.add_column(
        'evaluation_results',
        sa.Column('is_out_of_scope', sa.Boolean(), nullable=True, server_default=sa.text('false')),
    )


def downgrade() -> None:
    op.drop_column('evaluation_results', 'is_out_of_scope')
    op.drop_column('evaluation_results', 'is_multihop')
