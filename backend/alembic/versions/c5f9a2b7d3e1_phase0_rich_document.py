"""phase0 rich document fields

阶段 0 兼容数据模型：为练习题目新增富文本文档字段，为练习新增迁移状态字段。
旧字段（content_snapshot / options_snapshot / practice_content_blocks）保持原样，
迁移稳定前不删除、不覆盖，支持回退读取。

Revision ID: c5f9a2b7d3e1
Revises: 7be1dc9c4638
Create Date: 2026-08-30 01:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5f9a2b7d3e1'
down_revision: Union[str, Sequence[str], None] = '7be1dc9c4638'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('practice_questions') as batch_op:
        batch_op.add_column(sa.Column('rich_document', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('doc_version', sa.Integer(), nullable=False,
                                      server_default='0'))
    with op.batch_alter_table('practices') as batch_op:
        batch_op.add_column(sa.Column('migration_status', sa.String(length=20),
                                      nullable=False, server_default='pending'))
        batch_op.add_column(sa.Column('migration_note', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('migrated_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('practices') as batch_op:
        batch_op.drop_column('migrated_at')
        batch_op.drop_column('migration_note')
        batch_op.drop_column('migration_status')
    with op.batch_alter_table('practice_questions') as batch_op:
        batch_op.drop_column('doc_version')
        batch_op.drop_column('rich_document')
