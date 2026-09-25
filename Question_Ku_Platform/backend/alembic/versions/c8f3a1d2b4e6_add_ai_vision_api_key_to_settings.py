"""add ai_vision_api_key to settings

Revision ID: c8f3a1d2b4e6
Revises: b3e7c1d9f2a4
Create Date: 2026-09-25 10:00:00.000000

视觉模型的独立 API Key。为什么不复用 ai_api_key：文本与视觉模型常常属**不同
供应商**（gpt-4o 走 OpenAI、qwen-vl-max 走 DashScope），共用一个 Key 只会在
调用时报 401，而且报错指向的是视觉模型，排查时很难想到是 Key 混了。

允许为空 —— 留空时运行时回退到 ai_api_key（get_vision_config），两家用同一
家供应商的老配置**行为完全不变**，无需迁移数据。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8f3a1d2b4e6'
down_revision: Union[str, Sequence[str], None] = 'b3e7c1d9f2a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ai_vision_api_key', sa.String(length=500), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.drop_column('ai_vision_api_key')
