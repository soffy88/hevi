"""persist bounded autonomous-repair runs and scoped actions"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4e5f60718293"
down_revision: str | None = "3d4e5f607182"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "repair_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("video_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "production_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("productions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("policy_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("profile", sa.String(32), nullable=False, server_default="standard"),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempts_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("budget_limit_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("spent_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("residual_severity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("residual_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stop_reason", sa.String(64), nullable=True),
        sa.Column(
            "snapshot_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("task_id", name="uq_repair_runs_task_id"),
    )
    op.create_index("ix_repair_runs_production_id", "repair_runs", ["production_id"])
    op.create_table(
        "repair_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "repair_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("repair_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(128), nullable=False),
        sa.Column("failure_code", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("expected_gain", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="planned"),
        sa.Column(
            "details_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_repair_actions_run_id", "repair_actions", ["repair_run_id"])


def downgrade() -> None:
    op.drop_index("ix_repair_actions_run_id", table_name="repair_actions")
    op.drop_table("repair_actions")
    op.drop_index("ix_repair_runs_production_id", table_name="repair_runs")
    op.drop_table("repair_runs")

