"""add mineru params to settings

Revision ID: b3e7c1d9f2a4
Revises: f7a2b9c4e1d8
Create Date: 2026-09-23 20:00:00.000000

MinerU 通道的解析参数。默认值就是官方默认值，所以迁移后行为与迁移前一致。

为什么这些参数值得做成可配（而不是写死在客户端里）：
- model_version：vlm 把选择题的 A/B/C/D 拆成各自独立的块，pipeline 会把它们挤成
  一行（"…匀速直线运动B. 在0～40s…"），对下游逐题结构化差别明显；
- language：手写体试卷要 ch_server，英文卷用 en 更准；
- enable_formula / enable_table：默认开，英语等非理科文档可以关掉省时间。

全部 NOT NULL 且带 server_default：老库迁移时一次性补上，读出来不会是 NULL。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3e7c1d9f2a4'
down_revision: Union[str, Sequence[str], None] = 'f7a2b9c4e1d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'mineru_model_version',
                sa.String(length=20),
                nullable=False,
                server_default='vlm',
            )
        )
        batch_op.add_column(
            sa.Column(
                'mineru_language',
                sa.String(length=20),
                nullable=False,
                server_default='ch',
            )
        )
        batch_op.add_column(
            sa.Column(
                'mineru_enable_formula',
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
        batch_op.add_column(
            sa.Column(
                'mineru_enable_table',
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.drop_column('mineru_enable_table')
        batch_op.drop_column('mineru_enable_formula')
        batch_op.drop_column('mineru_language')
        batch_op.drop_column('mineru_model_version')
