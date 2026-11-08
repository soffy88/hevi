"""merge the two canvas-era alembic heads

Before this migration the tree had two heads (``eaff3a92445c`` shot verdict
cost and ``g1c2d3e4f5a6`` case-learning owner fences) with no merge point.
The canvas MVP adds tables that must sit on a single head, so this empty
merge revision joins them. No schema change.

Revision ID: c4a11ab1e001
Revises: eaff3a92445c, g1c2d3e4f5a6
Create Date: 2026-11-08 09:00:00.000000

"""

from collections.abc import Sequence

revision: str = "c4a11ab1e001"
down_revision: str | Sequence[str] | None = ("eaff3a92445c", "g1c2d3e4f5a6")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
