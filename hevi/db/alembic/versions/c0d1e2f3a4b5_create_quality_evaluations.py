"""Persist quality evidence, violations and bounded repair plans."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# ``c0d1e2f3a4b5`` is already the published receipt migration.  Keeping two
# files with that revision makes Alembic unable to load the graph at all.  The
# quality migration keeps its original parent and receives a new identity so
# existing databases stamped on the receipt branch remain upgradeable.
revision: str = "c0d1e2f3a4b9"
down_revision: str | None = "b8c9d0e1f234"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "production_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("productions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("production_revisions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("video_tasks.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("attempt_id", sa.String(128), nullable=True),
        sa.Column("scope", sa.String(255), nullable=False, server_default="production"),
        sa.Column("evaluator", sa.String(128), nullable=False, server_default="hevi.quality"),
        sa.Column("status", sa.String(32), nullable=False, server_default="completed"),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("residual_severity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("residual_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evidence_artifact_id", sa.Text(), nullable=True),
        sa.Column(
            "details_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_evaluations_task_created", "evaluations", ["task_id", "created_at"])
    op.create_index(
        "ix_evaluations_production_created", "evaluations", ["production_id", "created_at"]
    )

    op.create_table(
        "violations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "evaluation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evaluations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("taxonomy", sa.String(128), nullable=False),
        sa.Column("severity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("repairable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("scope", sa.String(255), nullable=False, server_default=""),
        sa.Column(
            "details_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_violations_evaluation", "violations", ["evaluation_id", "created_at"])
    op.create_index("ix_violations_taxonomy", "violations", ["taxonomy", "created_at"])

    op.create_table(
        "repair_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "production_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("productions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("video_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "evaluation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evaluations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("violation_set_hash", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(255), nullable=False, server_default="production"),
        sa.Column("expected_gain", sa.Float(), nullable=False, server_default="0"),
        sa.Column("max_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="planned"),
        sa.Column(
            "decision_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_repair_plans_task_created", "repair_plans", ["task_id", "created_at"])
    op.create_index(
        "ix_repair_plans_production_created", "repair_plans", ["production_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_repair_plans_production_created", table_name="repair_plans")
    op.drop_index("ix_repair_plans_task_created", table_name="repair_plans")
    op.drop_table("repair_plans")
    op.drop_index("ix_violations_taxonomy", table_name="violations")
    op.drop_index("ix_violations_evaluation", table_name="violations")
    op.drop_table("violations")
    op.drop_index("ix_evaluations_production_created", table_name="evaluations")
    op.drop_index("ix_evaluations_task_created", table_name="evaluations")
    op.drop_table("evaluations")
