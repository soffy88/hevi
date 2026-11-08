"""Merge the two Alembic heads into a single head.

Heads merged:
- eaff3a92445c: add nullable cost_usd to shot_verdict.
- g1c2d3e4f5a6: database-enforced owner fences for intelligence evidence
  projections.

This is a pure merge revision: no DDL of its own. Upgrading a database
stamped at g1c2d3e4f5a6 to this head applies the eaff3a92445c upgrade
(add cost_usd) and then this no-op merge, leaving a single head so that
`alembic upgrade head` no longer fails with multiple heads.

Revision ID: 03dc5c47f82c
Revises: eaff3a92445c, g1c2d3e4f5a6
Create Date: 2026-11-05 00:00:00.000000

"""

from collections.abc import Sequence

revision: str = "03dc5c47f82c"
down_revision: tuple[str, str] = ("eaff3a92445c", "g1c2d3e4f5a6")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
