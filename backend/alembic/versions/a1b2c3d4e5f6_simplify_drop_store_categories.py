"""simplify: drop categories/user_store, remove is_global/category_id/agent

Revision ID: a1b2c3d4e5f6
Revises: da0a60668747
Create Date: 2026-06-22 10:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'da0a60668747'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 删除 messages.agent 字段
    op.drop_column('messages', 'agent')

    # 2. 删除 knowledge_bases 的 category_id 和 is_global
    op.drop_constraint(
        'knowledge_bases_category_id_fkey', 'knowledge_bases', type_='foreignkey'
    )
    op.drop_column('knowledge_bases', 'category_id')
    op.drop_column('knowledge_bases', 'is_global')

    # 3. 删除 owner_id 的可空约束（现在必须不为空）
    op.alter_column('knowledge_bases', 'owner_id',
                    existing_type=postgresql.UUID(),
                    nullable=False)

    # 4. 删除 categories 表
    op.drop_table('categories')

    # 5. 删除 user_store 表
    op.drop_table('user_store')


def downgrade() -> None:
    # 1. 恢复 user_store 表
    op.create_table('user_store',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('namespace', sa.String(length=100), nullable=False),
        sa.Column('key', sa.String(length=200), nullable=False),
        sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_store_user_ns_key', 'user_store', ['user_id', 'namespace', 'key'], unique=True)

    # 2. 恢复 categories 表
    op.create_table('categories',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )

    # 3. 恢复 knowledge_bases 的 category_id 和 is_global
    op.add_column('knowledge_bases', sa.Column('category_id', sa.Integer(), nullable=True))
    op.add_column('knowledge_bases', sa.Column('is_global', sa.Boolean(), nullable=True))
    op.create_foreign_key(
        'knowledge_bases_category_id_fkey', 'knowledge_bases', 'categories',
        ['category_id'], ['id']
    )

    # 4. 恢复 messages.agent 字段
    op.add_column('messages', sa.Column('agent', sa.String(length=50), nullable=True))
