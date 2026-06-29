"""create assets table (E4 asset_reference_inject backing store)

Layer4 self-managed asset store for per-shot reference injection. Covers the
E4 asset_refs taxonomy: character / scene / voice / prop / fx. `data` JSONB holds
type-specific payload (e.g. reference_images, voice_ref path, prompt hints) that
the asset_loader returns to oskill.asset_reference_inject.

Revision ID: a2c8e1f4b730
Revises: f1a7c3e9b210
Create Date: 2026-06-29 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'a2c8e1f4b730'
down_revision: str | None = 'f1a7c3e9b210'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'assets',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('asset_type', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default='{}'),
        sa.Column('user_id', sa.String(length=255), nullable=True),  # NULL = official/shared
        sa.Column('is_official', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_assets_type', 'assets', ['asset_type'])
    op.create_index('ix_assets_user', 'assets', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_assets_user', table_name='assets')
    op.drop_index('ix_assets_type', table_name='assets')
    op.drop_table('assets')
