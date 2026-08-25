"""add durable scheduler inputs and dispatch decision audit"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "6a718293a4b5"
down_revision: str | None = "5f60718293a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "video_tasks",
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("video_tasks", sa.Column("deadline_at", sa.DateTime(), nullable=True))
    op.add_column("video_tasks", sa.Column("available_at", sa.DateTime(), nullable=True))
    op.add_column(
        "video_tasks",
        sa.Column("resource_class", sa.String(32), nullable=False, server_default="any"),
    )
    op.add_column(
        "video_tasks",
        sa.Column("required_vram_mb", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "video_tasks",
        sa.Column("expected_cost_usd", sa.Numeric(18, 6), nullable=False, server_default="0"),
    )
    op.add_column(
        "video_tasks",
        sa.Column("tenant_weight", sa.Float(), nullable=False, server_default="1"),
    )
    op.add_column("video_tasks", sa.Column("warm_provider", sa.String(128), nullable=True))
    op.create_index(
        "ix_video_tasks_scheduler_queue",
        "video_tasks",
        ["status", "priority", "deadline_at", "queued_at"],
    )
    op.create_check_constraint(
        "ck_video_tasks_scheduler_resource_class",
        "video_tasks",
        "resource_class IN ('any', 'cpu', 'gpu-video', 'gpu-audio', 'cloud')",
    )
    op.create_check_constraint(
        "ck_video_tasks_scheduler_numbers",
        "video_tasks",
        "required_vram_mb >= 0 AND expected_cost_usd >= 0 AND tenant_weight > 0",
    )

    op.create_table(
        "scheduler_dispatches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("video_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("worker_id", sa.String(128), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "decision_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_scheduler_dispatches_task_created",
        "scheduler_dispatches",
        ["task_id", "created_at"],
    )
    op.create_index(
        "ix_scheduler_dispatches_worker_created",
        "scheduler_dispatches",
        ["worker_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_scheduler_dispatches_worker_created", table_name="scheduler_dispatches")
    op.drop_index("ix_scheduler_dispatches_task_created", table_name="scheduler_dispatches")
    op.drop_table("scheduler_dispatches")
    op.drop_constraint(
        "ck_video_tasks_scheduler_numbers", "video_tasks", type_="check"
    )
    op.drop_constraint(
        "ck_video_tasks_scheduler_resource_class", "video_tasks", type_="check"
    )
    op.drop_index("ix_video_tasks_scheduler_queue", table_name="video_tasks")
    op.drop_column("video_tasks", "warm_provider")
    op.drop_column("video_tasks", "tenant_weight")
    op.drop_column("video_tasks", "expected_cost_usd")
    op.drop_column("video_tasks", "required_vram_mb")
    op.drop_column("video_tasks", "resource_class")
    op.drop_column("video_tasks", "available_at")
    op.drop_column("video_tasks", "deadline_at")
    op.drop_column("video_tasks", "priority")
