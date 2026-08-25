"""Persist provider health, quota and execution outcomes for policy routing."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9d0e1f2a3b4c"
down_revision: str | None = "8c93d4e5f607"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_runtime_state",
        sa.Column("provider_id", sa.String(128), primary_key=True),
        sa.Column("health", sa.Numeric(8, 6), nullable=True),
        sa.Column("balance_usd", sa.Numeric(18, 6), nullable=True),
        sa.Column("quota_remaining", sa.Integer(), nullable=True),
        sa.Column("p95_latency_ms", sa.Numeric(18, 6), nullable=True),
        sa.Column("error_rate", sa.Numeric(8, 6), nullable=True),
        sa.Column("quality_score", sa.Numeric(8, 6), nullable=True),
        sa.Column("source", sa.String(128), nullable=False, server_default="runtime"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_table(
        "provider_outcomes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider_id", sa.String(128), nullable=False),
        sa.Column("task_class", sa.String(128), nullable=False, server_default="unknown"),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("latency_ms", sa.Numeric(18, 6), nullable=True),
        sa.Column("cost_usd", sa.Numeric(18, 6), nullable=True),
        sa.Column("quality_score", sa.Numeric(8, 6), nullable=True),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column(
            "metadata",
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
    op.create_index(
        "ix_provider_outcomes_provider_created",
        "provider_outcomes",
        ["provider_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_provider_outcomes_provider_created", table_name="provider_outcomes")
    op.drop_table("provider_outcomes")
    op.drop_table("provider_runtime_state")
