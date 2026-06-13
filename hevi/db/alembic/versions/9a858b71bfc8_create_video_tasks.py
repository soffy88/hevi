"""create_video_tasks

Revision ID: 9a858b71bfc8
Revises: 
Create Date: 2026-06-13 16:17:55.602495

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '9a858b71bfc8'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'video_tasks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('topic', sa.String(length=255), nullable=False),
        sa.Column('duration_archetype', sa.String(length=50), nullable=False),
        sa.Column('video_provider', sa.String(length=50), nullable=False),
        sa.Column('audio_provider', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('progress_pct', sa.Float(), nullable=False),
        sa.Column('total_shots', sa.Integer(), nullable=False),
        sa.Column('completed_shots', sa.Integer(), nullable=False),
        sa.Column('result_video_path', sa.String(length=512), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('config_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table(
        'shot_states',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('task_id', sa.UUID(), nullable=False),
        sa.Column('shot_index', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('output_path', sa.String(length=512), nullable=True),
        sa.Column('reference_set_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['task_id'], ['video_tasks.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('shot_states')
    op.drop_table('video_tasks')
