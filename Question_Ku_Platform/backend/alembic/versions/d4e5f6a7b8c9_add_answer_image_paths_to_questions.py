"""add answer_image_paths to questions

Revision ID: d4e5f6a7b8c9
Revises: c1d2e3f4a5b6
Create Date: 2026-09-12 02:00:00.000000

新增 questions.answer_image_paths（JSON 数组，存绝对路径）。

背景：答案区的插图原先从来没被抽取过。答案是图的题（卷面「【答案】」下面
直接是一幅图，或答案只写「如上图所示」）在产物里连图都没有，answer 字段
只能为空或一句没有指向的话。api_extract 通道现已把答案区插图裁出来挂在
ExtractItemData.answer_figures 上，这里给它一个落库的位置。

存绝对路径与 card_image_path 保持一致；QuestionResponse 的
transform_asset_urls 会复用 resolve_card_image_path 把它转成
/api/ocr-assets/{source_id}/... 供前端直接访问。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('questions', schema=None) as batch_op:
        # server_default 让迁移前的存量行拿到 '[]' 而不是 NULL —— 前端与
        # schema 都按「列表」处理，NULL 会在序列化时炸。
        batch_op.add_column(
            sa.Column('answer_image_paths', sa.JSON(), nullable=True, server_default='[]')
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('questions', schema=None) as batch_op:
        batch_op.drop_column('answer_image_paths')
