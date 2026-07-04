"""create series + add series_id/episode_index to video_tasks

Series 资产化(§3 L2):第 N 集的载体。series 表 + video_tasks 加 series_id FK / episode_index。

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-07-04 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f3a4b5c6d7e8"
down_revision: str | None = "e2f3a4b5c6d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "series",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=True),
        sa.Column(
            "subject_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("style_preset", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("style_pack_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "spec_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("intro_template_id", sa.String(length=64), nullable=True),
        sa.Column("outro_template_id", sa.String(length=64), nullable=True),
        sa.Column("episode_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_series_user_id", "series", ["user_id"])

    op.add_column(
        "video_tasks",
        sa.Column("series_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("video_tasks", sa.Column("episode_index", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_video_tasks_series_id", "video_tasks", "series", ["series_id"], ["id"]
    )
    op.create_index("ix_video_tasks_series_id", "video_tasks", ["series_id"])


def downgrade() -> None:
    op.drop_index("ix_video_tasks_series_id", table_name="video_tasks")
    op.drop_constraint("fk_video_tasks_series_id", "video_tasks", type_="foreignkey")
    op.drop_column("video_tasks", "episode_index")
    op.drop_column("video_tasks", "series_id")
    op.drop_index("ix_series_user_id", table_name="series")
    op.drop_table("series")
