"""Persist execution attempts, checkpoints and the scheduler leader lease.

``video_tasks`` remains the user-facing task projection.  Ownership and
progress, however, belong to an attempt: a task may be claimed again by a
different worker without losing the last durable stage boundary.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7b8293a4b5c6"
down_revision: str | None = "6a718293a4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("video_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="claimed"),
        sa.Column("worker_id", sa.String(128), nullable=False),
        sa.Column("lease_token", sa.String(128), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("task_id", "attempt_no", name="uq_task_attempt_no"),
        sa.UniqueConstraint("lease_token", name="uq_task_attempt_lease_token"),
    )
    op.create_index(
        "ix_task_attempts_task_status",
        "task_attempts",
        ["task_id", "status", "created_at"],
    )
    op.create_index("ix_task_attempts_lease_until", "task_attempts", ["lease_until"])

    op.create_table(
        "attempt_checkpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_attempts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("video_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(128), nullable=False),
        sa.Column("progress_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("completed_shots", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_shots", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "state_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "artifact_manifest_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("attempt_id", "sequence", name="uq_attempt_checkpoint_sequence"),
    )
    op.create_index(
        "ix_attempt_checkpoints_task_latest",
        "attempt_checkpoints",
        ["task_id", "created_at", "sequence"],
    )

    op.add_column(
        "video_tasks",
        sa.Column("current_attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("video_tasks", sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("video_tasks", sa.Column("scheduler_score", sa.Float(), nullable=True))
    op.add_column(
        "video_tasks",
        sa.Column("scheduler_policy_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "video_tasks",
        sa.Column(
            "scheduler_decision_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_video_tasks_current_attempt",
        "video_tasks",
        "task_attempts",
        ["current_attempt_id"],
        ["id"],
        use_alter=True,
    )
    op.create_index(
        "ix_video_tasks_scheduled_queue",
        "video_tasks",
        ["status", "scheduled_at", "scheduler_score"],
    )

    op.create_table(
        "scheduler_leases",
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("scheduler_leases")
    op.drop_index("ix_video_tasks_scheduled_queue", table_name="video_tasks")
    op.drop_constraint("fk_video_tasks_current_attempt", "video_tasks", type_="foreignkey")
    op.drop_column("video_tasks", "scheduler_decision_json")
    op.drop_column("video_tasks", "scheduler_policy_version")
    op.drop_column("video_tasks", "scheduler_score")
    op.drop_column("video_tasks", "scheduled_at")
    op.drop_column("video_tasks", "current_attempt_id")
    op.drop_index("ix_attempt_checkpoints_task_latest", table_name="attempt_checkpoints")
    op.drop_table("attempt_checkpoints")
    op.drop_index("ix_task_attempts_lease_until", table_name="task_attempts")
    op.drop_index("ix_task_attempts_task_status", table_name="task_attempts")
    op.drop_table("task_attempts")
