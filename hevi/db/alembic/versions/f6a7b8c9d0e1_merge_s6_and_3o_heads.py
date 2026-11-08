"""Merge the S6 canvas head with the 3O conformance head.

Heads merged:
- c4a11ab1e002: canvas MVP tables (node/edge/artifact/revision/cost).
- 03dc5c47f82c: cost_usd on shot_verdict + owner fences.

Pure merge revision, no DDL of its own.  Needed because local main and
origin/main each merged the eaff3a92445c / g1c2d3e4f5a6 pair separately.

Revision ID: f6a7b8c9d0e1
Revises: 03dc5c47f82c, c4a11ab1e002
Create Date: 2026-11-08 11:15:00.000000
"""

from collections.abc import Sequence

revision: str = "f6a7b8c9d0e1"
down_revision: tuple[str, str] = ("03dc5c47f82c", "c4a11ab1e002")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
