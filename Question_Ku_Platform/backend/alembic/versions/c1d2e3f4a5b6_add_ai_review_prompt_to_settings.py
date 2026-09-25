"""add ai_review_prompt to settings

Revision ID: c1d2e3f4a5b6
Revises: b7c4e1f9a2d3
Create Date: 2026-09-10 15:00:00.000000

补齐一处既有 schema 漂移：``Settings.ai_review_prompt``（AI 题目修正功能
引入的自定义复核提示词，见 ``app/models/settings.py`` 与 ``app/services/ai_correct.py``）
只存在于模型定义中，此前没有任何迁移创建它，导致真实库 ``data/db.sqlite3``
缺列，ORM 读 settings 直接抛 ``no such column: settings.ai_review_prompt``。

历史包袱：如果中途执行过 downgrade/upgrade 往返（迁移只能按自身 DDL 重建表），
手工加过的列会被抹掉，因此这里必须补成可复现的迁移。

字段可空，无默认值，不影响既有数据。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'b7c4e1f9a2d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ai_review_prompt', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.drop_column('ai_review_prompt')
