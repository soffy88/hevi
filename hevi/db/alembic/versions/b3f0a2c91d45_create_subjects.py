"""create_subjects

Revision ID: b3f0a2c91d45
Revises: 9a858b71bfc8
Create Date: 2026-06-14 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'b3f0a2c91d45'
down_revision: str | None = '9a858b71bfc8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'subjects',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('subject_type', sa.String(length=50), nullable=False),
        sa.Column('reference_images', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('user_id', sa.String(length=255), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_subjects_subject_type', 'subjects', ['subject_type'])
    op.create_index('ix_subjects_user_id', 'subjects', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_subjects_user_id', table_name='subjects')
    op.drop_index('ix_subjects_subject_type', table_name='subjects')
    op.drop_table('subjects')
