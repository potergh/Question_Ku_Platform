"""add sub_questions to questions

Revision ID: a7f3c2d1b9e4
Revises: c8f3a1d2b4e6
Create Date: 2026-09-25 10:00:00.000000

新增 questions.sub_questions（JSON，可空）。

背景：英语语篇题（完形填空 / 阅读理解 / 任务型阅读 / 综合填空）本质是
「一篇材料挂多个各自带编号的小题」。之前要么把整篇压成一条（小题选项全丢），
要么把每个小题切成独立单题（题目与选项分散），都不是用户要的「完整一道」。
两级模型：content 存共享材料（文章/长对话），sub_questions 存各小题
[{"label","stem","options":[{"label","content"}],"answer","explanation"}]。

普通题为 NULL，所有既有渲染/导出仍走单题路径，物理等学科零影响。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7f3c2d1b9e4'
down_revision: Union[str, Sequence[str], None] = 'c8f3a1d2b4e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('questions', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('sub_questions', sa.JSON(), nullable=True)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('questions', schema=None) as batch_op:
        batch_op.drop_column('sub_questions')
