"""create execution_plans table - INSERT ONLY, immutable versions

P0-E: Execution plan versioning.  Same (production, revision, plan_version) cannot be ON CONFLICT UPDATE.
New versions only via ExecutionPlan.create() or from_existing() factory methods.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c0d1e2f3a4b8"
down_revision: str | None = "c0d1e2f3a4b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "execution_plans",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("production_id", sa.UUID(), nullable=False),
        sa.Column("revision_id", sa.UUID(), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("plan_json", sa.JSON(), nullable=False),
        sa.Column("plan_hash", sa.Text(), nullable=False),
        sa.Column("parent_plan_id", sa.UUID(), nullable=True),
        sa.Column("created_by_attempt_id", sa.UUID(), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=False, server_default="initial"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("production_id", "revision_id", "plan_version", name="uq_exec_plan_version"),
    )
    op.create_index("ix_exec_production", "execution_plans", ["production_id"])
    op.create_index("ix_exec_revision", "execution_plans", ["revision_id"])


def downgrade() -> None:
    op.drop_index("ix_exec_revision", table_name="execution_plans")
    op.drop_index("ix_exec_production", table_name="execution_plans")
    op.drop_table("execution_plans")
