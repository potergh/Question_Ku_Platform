"""add layout_document to practices

Revision ID: a1b2c3d4e5f6
Revises: e1b2c3d4f5a6
Create Date: 2026-08-31

阶段 5：整册编排布局（架构 A，线性块序列），与旧 sections 并存可回退。
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "e1b2c3d4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("practices") as batch:
        batch.add_column(sa.Column("layout_document", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("practices") as batch:
        batch.drop_column("layout_document")
