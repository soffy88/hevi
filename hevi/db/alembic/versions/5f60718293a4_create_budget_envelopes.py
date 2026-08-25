"""add production/stage/attempt budget envelopes and immutable ledger"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5f60718293a4"
down_revision: str | None = "4e5f60718293"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "production_budgets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "production_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("productions.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("hard_limit_usd", sa.Numeric(18, 6), nullable=False),
        sa.Column("soft_limit_usd", sa.Numeric(18, 6), nullable=False),
        sa.Column("reserved_usd", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("spent_usd", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("retake_pool_usd", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("retake_reserved_usd", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("retake_spent_usd", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("hard_limit_usd > 0", name="ck_production_budget_hard_positive"),
        sa.CheckConstraint("soft_limit_usd >= 0", name="ck_production_budget_soft_nonnegative"),
        sa.CheckConstraint("reserved_usd >= 0 AND spent_usd >= 0", name="ck_production_budget_balances_nonnegative"),
        sa.CheckConstraint(
            "retake_reserved_usd >= 0 AND retake_spent_usd >= 0 AND retake_pool_usd >= 0",
            name="ck_production_budget_retake_nonnegative",
        ),
    )
    op.create_index("ix_production_budgets_production_id", "production_budgets", ["production_id"])

    op.create_table(
        "stage_budgets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "production_budget_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("production_budgets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("allocation_usd", sa.Numeric(18, 6), nullable=False),
        sa.Column("reserved_usd", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("spent_usd", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("borrow_policy", sa.String(32), nullable=False, server_default="none"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("production_budget_id", "category", name="uq_stage_budget_category"),
        sa.CheckConstraint("allocation_usd >= 0", name="ck_stage_budget_allocation_nonnegative"),
        sa.CheckConstraint("reserved_usd >= 0 AND spent_usd >= 0", name="ck_stage_budget_balances_nonnegative"),
        sa.CheckConstraint(
            "borrow_policy IN ('none', 'production_remaining', 'retake_pool_only')",
            name="ck_stage_budget_borrow_policy",
        ),
    )
    op.create_index("ix_stage_budgets_production_budget_id", "stage_budgets", ["production_budget_id"])

    op.create_table(
        "budget_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "production_budget_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("production_budgets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("video_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("stage_category", sa.String(64), nullable=False),
        sa.Column("attempt_key", sa.String(255), nullable=False),
        sa.Column("estimated_cost_usd", sa.Numeric(18, 6), nullable=False),
        sa.Column("reserved_cost_usd", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("actual_cost_usd", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("refunded_cost_usd", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("provider_cost_ref", sa.String(255), nullable=True),
        sa.Column("is_retake", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("borrowed_usd", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="reserved"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("production_budget_id", "attempt_key", name="uq_budget_attempt_key"),
        sa.CheckConstraint("estimated_cost_usd > 0", name="ck_budget_attempt_estimate_positive"),
        sa.CheckConstraint("reserved_cost_usd >= 0 AND actual_cost_usd >= 0", name="ck_budget_attempt_costs_nonnegative"),
        sa.CheckConstraint("status IN ('reserved', 'settled', 'released')", name="ck_budget_attempt_status"),
    )
    op.create_index("ix_budget_attempts_task_id", "budget_attempts", ["task_id"])
    op.create_index("ix_budget_attempts_status", "budget_attempts", ["status"])

    op.create_table(
        "budget_ledger",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "production_budget_id",
            postgresql.UUID(as_uuid=True),
            # Financial history is retained; deleting a production with a
            # ledger is intentionally blocked instead of cascading history.
            sa.ForeignKey("production_budgets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("budget_attempts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("stage_category", sa.String(64), nullable=True),
        sa.Column("entry_type", sa.String(16), nullable=False),
        sa.Column("amount_usd", sa.Numeric(18, 6), nullable=False),
        sa.Column("external_ref", sa.String(255), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "entry_type IN ('reserve', 'consume', 'release', 'refund', 'adjustment')",
            name="ck_budget_ledger_entry_type",
        ),
    )
    op.create_index(
        "ix_budget_ledger_budget_created",
        "budget_ledger",
        ["production_budget_id", "created_at"],
    )
    op.create_index("ix_budget_ledger_external_ref", "budget_ledger", ["external_ref"])

    # Application code never updates/deletes ledger rows.  This database guard
    # makes the append-only invariant survive accidental ORM/admin mutations.
    op.execute(
        """
        CREATE FUNCTION prevent_budget_ledger_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'budget_ledger is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER budget_ledger_append_only
        BEFORE UPDATE OR DELETE ON budget_ledger
        FOR EACH ROW EXECUTE FUNCTION prevent_budget_ledger_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS budget_ledger_append_only ON budget_ledger")
    op.execute("DROP FUNCTION IF EXISTS prevent_budget_ledger_mutation()")
    op.drop_index("ix_budget_ledger_external_ref", table_name="budget_ledger")
    op.drop_index("ix_budget_ledger_budget_created", table_name="budget_ledger")
    op.drop_table("budget_ledger")
    op.drop_index("ix_budget_attempts_status", table_name="budget_attempts")
    op.drop_index("ix_budget_attempts_task_id", table_name="budget_attempts")
    op.drop_table("budget_attempts")
    op.drop_index("ix_stage_budgets_production_budget_id", table_name="stage_budgets")
    op.drop_table("stage_budgets")
    op.drop_index("ix_production_budgets_production_id", table_name="production_budgets")
    op.drop_table("production_budgets")
