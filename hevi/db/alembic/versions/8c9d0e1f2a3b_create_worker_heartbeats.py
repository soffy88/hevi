"""Persist process-level worker heartbeats for readiness."""

from collections.abc import Sequence

from alembic import op

revision: str = "8c9d0e1f2a3b"
down_revision: str | None = "f7a8b9c0d1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS worker_heartbeats (
            worker_id VARCHAR(128) PRIMARY KEY,
            service VARCHAR(32) NOT NULL,
            last_heartbeat_at TIMESTAMPTZ NOT NULL,
            status VARCHAR(32) NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS ix_worker_heartbeats_service_status_heartbeat
            ON worker_heartbeats (service, status, last_heartbeat_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS worker_heartbeats")
