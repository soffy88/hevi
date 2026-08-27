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
    # A previous graph branch created the same table with mutable ``status``
    # and ``compiled_at`` columns.  This migration is intentionally
    # idempotent so a clean database and an already stamped branch converge on
    # the same immutable contract.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS execution_plans (
            id UUID PRIMARY KEY,
            production_id UUID NOT NULL,
            revision_id UUID NOT NULL,
            plan_version INTEGER NOT NULL,
            plan_json JSONB NOT NULL,
            plan_hash TEXT NOT NULL,
            parent_plan_id UUID NULL,
            created_by_attempt_id UUID NULL,
            change_reason TEXT NOT NULL DEFAULT 'initial',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("ALTER TABLE execution_plans ADD COLUMN IF NOT EXISTS plan_hash TEXT")
    op.execute("ALTER TABLE execution_plans ADD COLUMN IF NOT EXISTS parent_plan_id UUID")
    op.execute(
        "ALTER TABLE execution_plans ADD COLUMN IF NOT EXISTS created_by_attempt_id UUID"
    )
    op.execute(
        "ALTER TABLE execution_plans ADD COLUMN IF NOT EXISTS change_reason TEXT "
        "NOT NULL DEFAULT 'initial'"
    )
    op.execute(
        "ALTER TABLE execution_plans ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ "
        "NOT NULL DEFAULT now()"
    )
    op.execute("ALTER TABLE execution_plans DROP COLUMN IF EXISTS status")
    op.execute("ALTER TABLE execution_plans DROP COLUMN IF EXISTS compiled_at")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute(
        "UPDATE execution_plans SET plan_hash = encode(digest(convert_to(plan_json::text, 'UTF8'), 'sha256'), 'hex') "
        "WHERE plan_hash IS NULL OR plan_hash = ''"
    )
    op.execute("ALTER TABLE execution_plans ALTER COLUMN plan_hash SET NOT NULL")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_exec_plan_version "
        "ON execution_plans (production_id, revision_id, plan_version)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_exec_production ON execution_plans (production_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_exec_revision ON execution_plans (revision_id)"
    )


def downgrade() -> None:
    op.drop_index("ix_exec_revision", table_name="execution_plans")
    op.drop_index("ix_exec_production", table_name="execution_plans")
    op.drop_table("execution_plans")
