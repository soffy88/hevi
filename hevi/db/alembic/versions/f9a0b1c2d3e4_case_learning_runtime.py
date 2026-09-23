"""Persist durable case-analysis and case-reproduction executions.

The tables are projections owned by Video Intelligence.  Generation artifacts
and verdicts remain owned by HEVI's existing ``assets``/``artifacts`` and
``shot_verdict`` authorities.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f9a0b1c2d3e4"
down_revision: str | None = "e8f9a0b1c2d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A composite key lets PostgreSQL enforce that a child row belongs to the
    # same owner as its parent, rather than relying only on service checks.
    op.create_unique_constraint(
        "uq_video_cases_id_user", "video_cases", ["id", "user_id"]
    )

    op.create_table(
        "video_case_analyses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("analyzer_version", sa.String(128), nullable=False),
        sa.Column("analysis_json", postgresql.JSONB(), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["case_id", "user_id"],
            ["video_cases.id", "video_cases.user_id"],
            name="fk_case_analyses_case_owner",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id", "case_id", "idempotency_key",
            name="uq_case_analyses_owner_case_key",
        ),
    )
    op.create_index(
        "ix_case_analyses_owner_case", "video_case_analyses", ["user_id", "case_id"]
    )

    op.create_table(
        "case_reproductions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", sa.String(255), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("provider_id", sa.String(128), nullable=False),
        sa.Column("model_id", sa.String(255), nullable=False),
        sa.Column("model_version", sa.String(128), nullable=True),
        sa.Column("generation_mode", sa.String(64), nullable=False),
        sa.Column("compiled_prompt", sa.Text(), nullable=False),
        sa.Column("reference_binding_snapshot", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("generation_parameters", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("output_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cost_amount", sa.Numeric(18, 8), nullable=True),
        sa.Column("cost_currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("verdict_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("failure_code", sa.String(128), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["case_id", "user_id"],
            ["video_cases.id", "video_cases.user_id"],
            name="fk_case_reproductions_case_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["video_tasks.id"], name="fk_case_reproductions_task", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["output_asset_id"], ["assets.id"], name="fk_case_reproductions_output_asset", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["verdict_id"], ["shot_verdict.id"], name="fk_case_reproductions_verdict", ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "user_id", "case_id", "idempotency_key",
            name="uq_case_reproductions_owner_case_key",
        ),
    )
    op.create_index(
        "ix_case_reproductions_owner_case", "case_reproductions", ["user_id", "case_id"]
    )
    op.create_index(
        "ix_case_reproductions_task", "case_reproductions", ["task_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_case_reproductions_task", table_name="case_reproductions")
    op.drop_index("ix_case_reproductions_owner_case", table_name="case_reproductions")
    op.drop_table("case_reproductions")
    op.drop_index("ix_case_analyses_owner_case", table_name="video_case_analyses")
    op.drop_table("video_case_analyses")
    op.drop_constraint("uq_video_cases_id_user", "video_cases", type_="unique")
