"""create_showcase_items

首页画廊(gallery)读取 showcase_items 表,但此前**无迁移**、表在库中缺失,
gallery 查询会因表不存在而失败。这里补上迁移,统一由 alembic 管理。

Revision ID: b7e2c9a10f34
Revises: a2c8e1f4b730
Create Date: 2026-07-03 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7e2c9a10f34"
down_revision: str | None = "a2c8e1f4b730"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "showcase_items",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("media_url", sa.Text(), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "gen_params",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    # gallery 查询:WHERE is_active AND category = ? ORDER BY sort_order, created_at
    op.create_index(
        "ix_showcase_items_active_category", "showcase_items", ["is_active", "category"]
    )


def downgrade() -> None:
    op.drop_index("ix_showcase_items_active_category", table_name="showcase_items")
    op.drop_table("showcase_items")
