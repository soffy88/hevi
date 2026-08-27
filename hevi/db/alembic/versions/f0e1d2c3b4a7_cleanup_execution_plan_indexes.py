"""Remove duplicate indexes left by the converged execution-plan branches."""

from collections.abc import Sequence

from alembic import op

revision: str = "f0e1d2c3b4a7"
down_revision: str | None = "f0e1d2c3b4a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ``b8c9d0e1f234`` and the immutable-plan branch both created equivalent
    # indexes before the graph was merged. Keep the canonical names from
    # ``create_execution_plans.py`` and remove only the redundant copies.
    op.execute("DROP INDEX IF EXISTS ix_execution_plans_production_id")
    # The clean b8 migration created this name as a table constraint, while
    # some pre-existing databases carried it as a standalone index.
    op.execute(
        "ALTER TABLE execution_plans "
        "DROP CONSTRAINT IF EXISTS uq_execution_plan_revision"
    )
    op.execute("DROP INDEX IF EXISTS uq_execution_plan_revision")


def downgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_execution_plans_production_id "
        "ON execution_plans (production_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_execution_plan_revision "
        "ON execution_plans (production_id, revision_id, plan_version)"
    )
