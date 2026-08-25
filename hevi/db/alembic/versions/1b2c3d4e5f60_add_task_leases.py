"""add ownership leases for durable task execution"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1b2c3d4e5f60"
down_revision: str | None = "0a1b2c3d4e5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("video_tasks", sa.Column("worker_id", sa.String(128), nullable=True))
    op.add_column("video_tasks", sa.Column("lease_token", sa.String(128), nullable=True))
    op.add_column("video_tasks", sa.Column("lease_until", sa.DateTime(), nullable=True))
    op.add_column("video_tasks", sa.Column("heartbeat_at", sa.DateTime(), nullable=True))
    op.create_index("ix_video_tasks_lease_until", "video_tasks", ["lease_until"])


def downgrade() -> None:
    op.drop_index("ix_video_tasks_lease_until", table_name="video_tasks")
    op.drop_column("video_tasks", "heartbeat_at")
    op.drop_column("video_tasks", "lease_until")
    op.drop_column("video_tasks", "lease_token")
    op.drop_column("video_tasks", "worker_id")
