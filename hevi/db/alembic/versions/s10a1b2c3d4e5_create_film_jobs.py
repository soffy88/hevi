"""create_film_jobs (public-beta film quota)

S10 introduces the operator-approved public-beta pricing policy: free, no
payment, at most 5 finished films per account per day, 60 s per film and one
concurrent job.  ``film_jobs`` is the durable reservation/count table.

Revision ID: s10a1b2c3d4e5
Revises: s7a1b2c3d4e5
Create Date: 2026-11-09 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "s10a1b2c3d4e5"
down_revision: str | Sequence[str] | None = "s7a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "film_jobs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="running"),
        sa.Column("counts_as_film", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_film_jobs_user_status", "film_jobs", ["user_id", "status"]
    )
    op.create_index("ix_film_jobs_created_at", "film_jobs", ["created_at"])
    op.create_index("ix_film_jobs_task_id", "film_jobs", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_film_jobs_task_id", table_name="film_jobs")
    op.drop_index("ix_film_jobs_created_at", table_name="film_jobs")
    op.drop_index("ix_film_jobs_user_status", table_name="film_jobs")
    op.drop_table("film_jobs")
