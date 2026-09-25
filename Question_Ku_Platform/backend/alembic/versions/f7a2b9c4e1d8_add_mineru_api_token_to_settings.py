"""add mineru_api_token to settings

Revision ID: f7a2b9c4e1d8
Revises: d4e5f6a7b8c9
Create Date: 2026-09-23 18:00:00.000000

MinerU 识别通道的 Token（在 mineru.net 申请，接口用 Authorization: Bearer 鉴权）。

为什么不复用 ai_api_key：两者是**独立供应商**的凭证，没有任何关系。
MinerU 官方 API 不认 OpenAI 兼容的 Key，填错了只会在上传时才报 A0202，
排查成本远高于多存一列。允许为空 —— 不用这个通道时它就该是空的。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7a2b9c4e1d8'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('mineru_api_token', sa.String(length=500), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.drop_column('mineru_api_token')
