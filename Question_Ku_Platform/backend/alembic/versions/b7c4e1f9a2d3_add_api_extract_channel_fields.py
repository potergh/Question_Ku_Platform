"""add api_extract channel fields

Revision ID: b7c4e1f9a2d3
Revises: a1b2c3d4e5f6
Create Date: 2026-09-10 10:00:00.000000

新增大模型识别通道（job_type="api_extract"）所需的配置与配对字段：
- settings.ai_vision_model：视觉模型名，与文本模型分开配置
- settings.ai_vision_base_url：视觉模型端点（留空回退 ai_base_url）
- sources.role：paper / answer_doc，独立答案文档不产出 Question
- sources.extract_channel：local_ocr / api_extract，供 UI 与 retry 分发
- sources.companion_source_id：试卷指向其配对的答案文档（第三答案源）
- jobs.payload：任务参数 JSON（通道、学科、文档形态提示、配对信息）

Job.job_type 本身是自由字符串，新增取值无需迁移。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7c4e1f9a2d3'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'ai_vision_model',
                sa.String(length=100),
                nullable=False,
                server_default='qwen-vl-max',
            )
        )
        batch_op.add_column(sa.Column('ai_vision_base_url', sa.String(length=500), nullable=True))

    with op.batch_alter_table('sources', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('role', sa.String(length=20), nullable=False, server_default='paper')
        )
        batch_op.add_column(sa.Column('extract_channel', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('companion_source_id', sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            'fk_sources_companion_source_id',
            'sources',
            ['companion_source_id'],
            ['id'],
            ondelete='SET NULL',
        )

    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('payload', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.drop_column('payload')

    with op.batch_alter_table('sources', schema=None) as batch_op:
        batch_op.drop_constraint('fk_sources_companion_source_id', type_='foreignkey')
        batch_op.drop_column('companion_source_id')
        batch_op.drop_column('extract_channel')
        batch_op.drop_column('role')

    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.drop_column('ai_vision_base_url')
        batch_op.drop_column('ai_vision_model')
