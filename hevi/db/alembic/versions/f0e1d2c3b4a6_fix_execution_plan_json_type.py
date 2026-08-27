"""Align pre-closure execution plan payloads with the canonical JSONB schema."""

from collections.abc import Sequence

from alembic import op

revision: str = "f0e1d2c3b4a6"
down_revision: str | None = "f0e1d2c3b4a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Some databases were created from the earlier JSON contract before the
    # immutable plan migration was stamped. Converge those rows in place;
    # JSONB preserves the payload while making the production repository and
    # clean installs use the same PostgreSQL type.
    op.execute(
        """
        ALTER TABLE execution_plans
        ALTER COLUMN plan_json TYPE JSONB
        USING plan_json::jsonb
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE execution_plans
        ALTER COLUMN plan_json TYPE JSON
        USING plan_json::json
        """
    )
