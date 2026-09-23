"""Persist benchmark, pattern, template and learning projections.

The tables in this migration are intelligence projections.  They reference
HEVI's existing cases, reproductions, assets and shot verdicts; they do not
create a second generation, scoring, or job authority.
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "g0b1c2d3e4f5"
down_revision: str | None = "f9a0b1c2d3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid(name: str, **kwargs: Any) -> Any:
    return sa.Column(name, postgresql.UUID(as_uuid=True), **kwargs)


def upgrade() -> None:
    op.create_table(
        "benchmark_plans",
        _uuid("id", primary_key=True),
        sa.Column("workspace_id", sa.String(255), nullable=True),
        _uuid("user_id", nullable=False),
        _uuid("case_id", nullable=False),
        sa.Column("analysis_revision", sa.String(128), nullable=False),
        sa.Column("plan_json", postgresql.JSONB(), nullable=False),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id", "user_id"], ["video_cases.id", "video_cases.user_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "case_id", "plan_hash", name="uq_benchmark_plan_owner_case_hash"),
    )
    op.create_table(
        "case_benchmarks",
        _uuid("id", primary_key=True),
        sa.Column("workspace_id", sa.String(255), nullable=True),
        _uuid("user_id", nullable=False),
        _uuid("case_id", nullable=False),
        _uuid("benchmark_plan_id", nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("provider_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reproduction_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("failure_code", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id", "user_id"], ["video_cases.id", "video_cases.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["benchmark_plan_id"], ["benchmark_plans.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "case_id", "idempotency_key", name="uq_case_benchmark_owner_case_key"),
    )
    op.create_table(
        "case_benchmark_entries",
        _uuid("id", primary_key=True),
        _uuid("benchmark_id", nullable=False),
        _uuid("reproduction_id", nullable=False),
        sa.Column("provider_id", sa.String(128), nullable=False),
        sa.Column("model_id", sa.String(255), nullable=False),
        _uuid("verdict_id", nullable=True),
        sa.Column("dimension_comparison", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("cost_amount", sa.Numeric(18, 8), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["benchmark_id"], ["case_benchmarks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reproduction_id"], ["case_reproductions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["verdict_id"], ["shot_verdict.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("benchmark_id", "reproduction_id", name="uq_benchmark_entry_reproduction"),
    )

    op.create_table(
        "video_patterns",
        _uuid("id", primary_key=True),
        sa.Column("workspace_id", sa.String(255), nullable=True),
        _uuid("user_id", nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("conditions", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("structure", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("expected_effect", sa.Text(), nullable=False, server_default=""),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("positive_evidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("negative_evidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lifecycle_status", sa.String(32), nullable=False, server_default="candidate"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "name", name="uq_video_pattern_owner_name"),
    )
    op.create_table(
        "video_pattern_evidence",
        _uuid("id", primary_key=True),
        _uuid("pattern_id", nullable=False),
        _uuid("user_id", nullable=False),
        _uuid("case_id", nullable=False),
        _uuid("reproduction_id", nullable=False),
        _uuid("verdict_id", nullable=True),
        _uuid("production_learning_event_id", nullable=True),
        sa.Column("evidence_type", sa.String(32), nullable=False),
        sa.Column("evidence_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["pattern_id"], ["video_patterns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["video_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reproduction_id"], ["case_reproductions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["verdict_id"], ["shot_verdict.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("pattern_id", "case_id", "reproduction_id", "evidence_type", name="uq_pattern_evidence_source"),
    )

    op.create_table(
        "prompt_templates",
        _uuid("id", primary_key=True),
        sa.Column("workspace_id", sa.String(255), nullable=True),
        _uuid("user_id", nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("required_slots", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("optional_slots", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("structure", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("constraints", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("supported_modes", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("source_pattern_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("qualification_status", sa.String(32), nullable=False, server_default="candidate"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "name", "version", name="uq_prompt_template_revision"),
    )
    op.create_table(
        "template_qualification_runs",
        _uuid("id", primary_key=True),
        _uuid("template_id", nullable=False),
        _uuid("user_id", nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("case_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("reproduction_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("baseline_revision", sa.String(128), nullable=True),
        sa.Column("dimension_deltas", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("failure_code", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["template_id"], ["prompt_templates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "template_id", "idempotency_key", name="uq_template_qualification_key"),
    )

    op.create_table(
        "production_learning_events",
        _uuid("id", primary_key=True),
        sa.Column("workspace_id", sa.String(255), nullable=True),
        _uuid("user_id", nullable=False),
        sa.Column("production_id", sa.String(255), nullable=False),
        sa.Column("shot_id", sa.String(255), nullable=False),
        sa.Column("provider_id", sa.String(128), nullable=False),
        sa.Column("model_id", sa.String(255), nullable=False),
        sa.Column("model_version", sa.String(128), nullable=True),
        _uuid("template_id", nullable=True),
        sa.Column("template_revision", sa.Integer(), nullable=True),
        sa.Column("pattern_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("prompt_hash", sa.String(128), nullable=True),
        sa.Column("generation_mode", sa.String(64), nullable=False, server_default="unknown"),
        sa.Column("generation_cost", sa.Numeric(18, 8), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("retake_count", sa.Integer(), nullable=False, server_default="0"),
        _uuid("initial_verdict_id", nullable=True),
        _uuid("final_verdict_id", nullable=True),
        sa.Column("final_status", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["template_id"], ["prompt_templates.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["initial_verdict_id"], ["shot_verdict.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["final_verdict_id"], ["shot_verdict.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("user_id", "production_id", "shot_id", "idempotency_key", name="uq_learning_event_key"),
    )
    op.create_table(
        "retake_learning_records",
        _uuid("id", primary_key=True),
        sa.Column("workspace_id", sa.String(255), nullable=True),
        _uuid("user_id", nullable=False),
        sa.Column("production_id", sa.String(255), nullable=False),
        sa.Column("shot_id", sa.String(255), nullable=False),
        sa.Column("failure_reason_codes", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("retake_level", sa.String(64), nullable=False),
        sa.Column("retake_strategy", sa.String(255), nullable=False),
        sa.Column("changed_prompt", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("changed_provider", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("changed_reference", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("changed_duration", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("changed_camera", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _uuid("before_verdict_id", nullable=True),
        _uuid("after_verdict_id", nullable=True),
        sa.Column("cost_delta", sa.Numeric(18, 8), nullable=True),
        sa.Column("latency_delta", sa.Float(), nullable=True),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("multi_variable_retake", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["before_verdict_id"], ["shot_verdict.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["after_verdict_id"], ["shot_verdict.id"], ondelete="SET NULL"),
    )
    op.create_table(
        "provider_observed_stats",
        _uuid("id", primary_key=True),
        sa.Column("workspace_id", sa.String(255), nullable=True),
        _uuid("user_id", nullable=False),
        sa.Column("provider_id", sa.String(128), nullable=False),
        sa.Column("model_id", sa.String(255), nullable=False),
        sa.Column("model_version", sa.String(128), nullable=True),
        sa.Column("shot_type", sa.String(128), nullable=False, server_default="unknown"),
        sa.Column("style", sa.String(128), nullable=False, server_default="unknown"),
        sa.Column("generation_mode", sa.String(64), nullable=False, server_default="unknown"),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("identity_failure_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("action_failure_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("continuity_failure_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("style_failure_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("median_cost", sa.Numeric(18, 8), nullable=True),
        sa.Column("median_latency", sa.Float(), nullable=True),
        sa.Column("retake_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("last_observed_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "provider_id", "model_id", "model_version", "shot_type", "style", "generation_mode", name="uq_provider_observed_bucket"),
    )


def downgrade() -> None:
    for table in (
        "provider_observed_stats", "retake_learning_records", "production_learning_events",
        "template_qualification_runs", "prompt_templates", "video_pattern_evidence",
        "video_patterns", "case_benchmark_entries", "case_benchmarks", "benchmark_plans",
    ):
        op.drop_table(table)
