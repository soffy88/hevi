"""add_queued_at_to_video_tasks

Revision ID: e8f2c1a49d37
Revises: 5c498293bb2d
Create Date: 2026-06-19 10:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'e8f2c1a49d37'
down_revision: str | None = '5c498293bb2d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('video_tasks', sa.Column('queued_at', sa.DateTime(), nullable=True))
    op.add_column('video_tasks', sa.Column('queue_position', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('video_tasks', 'queue_position')
    op.drop_column('video_tasks', 'queued_at')
