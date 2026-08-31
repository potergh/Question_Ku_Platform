"""add is_baseline to practices

Revision ID: e1b2c3d4f5a6
Revises: c5f9a2b7d3e1
Create Date: 2026-08-30

阶段 0 验收决策：4 份基线练习保留在列表中但加标记（不隐藏）。
"""
from alembic import op
import sqlalchemy as sa

revision = "e1b2c3d4f5a6"
down_revision = "c5f9a2b7d3e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("practices") as batch:
        batch.add_column(sa.Column(
            "is_baseline", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("practices") as batch:
        batch.drop_column("is_baseline")
