"""restore the director work table used by the studio pipeline

The development database already contains this table under revision
``c9a1f4e78b23``.  The migration file was missing from the repository, which
made every Alembic command fail before the new automation/presenter migrations
could run.  This migration records the existing schema for clean rebuilds.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c9a1f4e78b23"
down_revision: str | None = "c7d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "director_works",
        sa.Column("work_id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(64), nullable=False, server_default=""),
        sa.Column("locked_through", sa.Integer(), nullable=False, server_default="-1"),
        sa.Column("visual_style", sa.String(64), nullable=False, server_default="realistic"),
        sa.Column("material_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("concept", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("screenplay", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("design_list", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("world_bible", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("scene_script", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("video_task_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_director_works_user_id", "director_works", ["user_id"])
    op.create_index("ix_director_works_video_task_id", "director_works", ["video_task_id"])


def downgrade() -> None:
    op.drop_index("ix_director_works_video_task_id", table_name="director_works")
    op.drop_index("ix_director_works_user_id", table_name="director_works")
    op.drop_table("director_works")
