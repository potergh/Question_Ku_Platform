"""drop handout tables

Revision ID: f3a1b2c4d5e6
Revises: db24daa9df4a
Create Date: 2026-08-28 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3a1b2c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'db24daa9df4a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_table('handout_items')
    op.drop_table('handouts')

    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.drop_column('handout_id')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('handout_id', sa.String(length=36), nullable=True))

    op.create_table('handouts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('subject', sa.String(length=50), nullable=True),
    sa.Column('target_student', sa.JSON(), nullable=True),
    sa.Column('teaching_notes', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('config', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('handout_items',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('handout_id', sa.String(length=36), nullable=False),
    sa.Column('order', sa.Integer(), nullable=False),
    sa.Column('item_type', sa.String(length=30), nullable=False),
    sa.Column('question_id', sa.String(length=36), nullable=True),
    sa.Column('question_snapshot', sa.JSON(), nullable=True),
    sa.Column('custom_content', sa.Text(), nullable=True),
    sa.Column('show_answer', sa.Boolean(), nullable=False),
    sa.Column('config', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['handout_id'], ['handouts.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
