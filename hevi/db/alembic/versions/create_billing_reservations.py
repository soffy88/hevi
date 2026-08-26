"""create billing_reservations table and add reserved_balance to credit_accounts

P0-D: Transactional billing reservation ledger
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c0d1e2f3a4b6"
down_revision: str | None = "c0d1e2f3a4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add reserved_balance to credit_accounts
    op.add_column(
        "credit_accounts",
        sa.Column("reserved_balance", sa.Integer(), nullable=False, default=0, server_default="0"),
    )

    # Create billing_reservations table
    op.create_table(
        "billing_reservations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("production_id", sa.UUID(), nullable=True),
        sa.Column("task_id", sa.UUID(), nullable=True),
        sa.Column("attempt_id", sa.UUID(), nullable=True),
        sa.Column("external_ref", sa.Text(), nullable=False, unique=True),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_amount_cents", sa.BigInteger(), nullable=False, default=0, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("amount_cents > 0", name="ck_billing_reservation_amount_positive"),
        sa.CheckConstraint(
            "status IN ('active','consumed','released','expired')",
            name="ck_billing_reservation_status"
        ),
    )
    op.create_index(
        "ix_billing_res_user", "billing_reservations", ["user_id"]
    )
    op.create_index(
        "ix_billing_res_production", "billing_reservations", ["production_id"]
    )
    op.create_index(
        "ix_billing_res_task", "billing_reservations", ["task_id"]
    )
    op.create_index(
        "ix_billing_res_attempt", "billing_reservations", ["attempt_id"]
    )
    op.create_index(
        "ix_billing_res_status", "billing_reservations", ["status"]
    )
    op.create_index(
        "ix_billing_res_expires", "billing_reservations", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_billing_res_expires", table_name="billing_reservations")
    op.drop_index("ix_billing_res_status", table_name="billing_reservations")
    op.drop_index("ix_billing_res_attempt", table_name="billing_reservations")
    op.drop_index("ix_billing_res_task", table_name="billing_reservations")
    op.drop_index("ix_billing_res_production", table_name="billing_reservations")
    op.drop_index("ix_billing_res_user", table_name="billing_reservations")
    op.drop_table("billing_reservations")
    op.drop_column("credit_accounts", "reserved_balance")
