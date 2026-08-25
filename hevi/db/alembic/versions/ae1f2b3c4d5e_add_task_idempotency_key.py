"""Add a durable per-user idempotency key to production tasks."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ae1f2b3c4d5e"
down_revision: str | None = "9d0e1f2a3b4c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "video_tasks",
        sa.Column("idempotency_key", sa.String(255), nullable=True),
    )
    op.create_index(
        "uq_video_tasks_user_idempotency_key",
        "video_tasks",
        ["user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_video_tasks_user_idempotency_key", table_name="video_tasks")
    op.drop_column("video_tasks", "idempotency_key")
