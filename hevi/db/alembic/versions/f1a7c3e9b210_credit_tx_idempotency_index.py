"""credit_tx idempotency unique index

Prevents double-charge / double-refund: a given (user_id, reference, tx_type)
ledger entry can exist at most once. reference is the task_id for consume/refund
and the order_ref for top-ups, so a retried consume/refund/webhook becomes a
no-op instead of mutating the balance twice.

Partial (WHERE reference IS NOT NULL) so manual/dev transactions without a
reference are unconstrained. Keyed by user_id so shared refs (e.g. the
"signup_bonus" constant) don't collide across users.

Revision ID: f1a7c3e9b210
Revises: e8f2c1a49d37
Create Date: 2026-06-29 00:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

revision: str = 'f1a7c3e9b210'
down_revision: str | None = 'e8f2c1a49d37'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "uq_credit_tx_idempotency"


def upgrade() -> None:
    # Pre-existing duplicate ledger rows (from the historical double-charge bug)
    # would block the unique index. Collapse each (user_id, reference, tx_type)
    # group to its earliest row. NOTE: this only repairs the ledger so the index
    # can be created; it does not retroactively recompute account balances.
    op.execute(
        "DELETE FROM credit_transactions "
        "WHERE ctid IN ("
        "  SELECT ctid FROM ("
        "    SELECT ctid, row_number() OVER ("
        "      PARTITION BY user_id, reference, tx_type ORDER BY created_at, ctid"
        "    ) AS rn"
        "    FROM credit_transactions"
        "    WHERE reference IS NOT NULL"
        "  ) t WHERE t.rn > 1"
        ")"
    )
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {_INDEX} "
        "ON credit_transactions (user_id, reference, tx_type) "
        "WHERE reference IS NOT NULL"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
