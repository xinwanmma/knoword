"""cleanup: drop graphrag_indexed 列（graph_retrieval 已删除，无人使用）

Revision ID: b1c2d3e4f5g6
Revises: 0b2d7d870f87
Create Date: 2026-06-26 15:30:00

清理：
- 删 knowledge_bases.graphrag_indexed（graph_retrieval.py 已删，无引用）

保留（用户要求）：
- evaluation_results.ragas_scores  ←  旧评估数据可能还在用
- evaluation_results.ragas_error   ←  同上
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = 'b1c2d3e4f5g6'
down_revision: Union[str, None] = '0b2d7d870f87'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('knowledge_bases', 'graphrag_indexed')


def downgrade() -> None:
    op.add_column(
        'knowledge_bases',
        sa.Column('graphrag_indexed', sa.Boolean(), nullable=True),
    )
