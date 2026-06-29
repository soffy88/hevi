from __future__ import annotations

import uuid
from typing import Any

from obase.persistence import PgPool, insert_one, query, read_one, transaction


class CreditRepository:
    def __init__(self, pool: PgPool) -> None:
        self._pool = pool

    async def get_or_create_account(self, user_id: str) -> dict[str, Any]:
        user_uuid = uuid.UUID(user_id)
        account = await read_one(
            self._pool, table="credit_accounts", id=user_uuid, id_column="user_id"
        )
        if not account:
            # Atomic create if not exists
            try:
                # Note: insert_one returns the 'returning' column value
                account_id = await insert_one(
                    self._pool, 
                    table="credit_accounts", 
                    data={"user_id": user_uuid, "balance": 0},
                    returning="user_id"
                )
                account = await read_one(
                    self._pool, table="credit_accounts", id=account_id, id_column="user_id"
                )
            except Exception:
                # Likely race condition, try reading again
                account = await read_one(
                    self._pool, table="credit_accounts", id=user_uuid, id_column="user_id"
                )
        return account or {}

    async def create_transaction(
        self, 
        user_id: str, 
        amount: int, 
        tx_type: str, 
        balance_after: int, 
        reference: str | None = None
    ) -> dict[str, Any]:
        data = {
            "user_id": uuid.UUID(user_id),
            "amount": amount,
            "tx_type": tx_type,
            "balance_after": balance_after,
            "reference": reference
        }
        tx_id = await insert_one(self._pool, table="credit_transactions", data=data, returning="id")
        return await read_one(self._pool, table="credit_transactions", id=tx_id) or {}

    async def update_balance_with_ledger(
        self, 
        user_id: str, 
        amount: int, 
        tx_type: str, 
        reference: str | None = None
    ) -> dict[str, Any]:
        """Atomically update balance and write transaction log."""
        user_uuid = uuid.UUID(user_id)
        async with transaction(self._pool) as conn:
            # 1. Lock account row for update
            row = await conn.fetchrow(
                "SELECT balance FROM credit_accounts WHERE user_id = $1 FOR UPDATE",
                user_uuid
            )
            # Idempotency: under the per-user row lock, if a ledger entry for this
            # (user, reference, tx_type) already exists, this op was already applied
            # — return it WITHOUT touching the balance (prevents double charge/refund).
            if reference is not None:
                existing = await conn.fetchrow(
                    "SELECT * FROM credit_transactions "
                    "WHERE user_id = $1 AND reference = $2 AND tx_type = $3",
                    user_uuid, reference, tx_type,
                )
                if existing:
                    return dict(existing)
            if not row:
                # If account doesn't exist, create it within the same transaction
                # Include created_at/updated_at if not handled by default/trigger
                await conn.execute(
                    "INSERT INTO credit_accounts (user_id, balance, updated_at) "
                    "VALUES ($1, 0, NOW())",
                    user_uuid
                )
                current_balance = 0
            else:
                current_balance = row["balance"]

            new_balance = current_balance + amount
            if new_balance < 0:
                raise ValueError("Insufficient credits")

            # 2. Update balance
            await conn.execute(
                "UPDATE credit_accounts SET balance = $1, updated_at = NOW() WHERE user_id = $2",
                new_balance, user_uuid
            )

            # 3. Insert transaction
            sql = (
                'INSERT INTO "credit_transactions" '
                '(id, user_id, amount, tx_type, balance_after, reference, created_at) '
                'VALUES ($1, $2, $3, $4, $5, $6, NOW()) RETURNING *'
            )
            tx_row = await conn.fetchrow(
                sql,
                uuid.uuid4(), user_uuid, amount, tx_type, new_balance, reference
            )
            return dict(tx_row)

    async def get_transaction(
        self, user_id: str, reference: str, tx_type: str
    ) -> dict[str, Any] | None:
        """Fetch a single ledger entry by its idempotency key, if any."""
        rows = await query(
            self._pool,
            sql=(
                "SELECT * FROM credit_transactions "
                "WHERE user_id = $1 AND reference = $2 AND tx_type = $3 LIMIT 1"
            ),
            params=[uuid.UUID(user_id), reference, tx_type],
        )
        return rows[0] if rows else None

    async def list_transactions(
        self,
        user_id: str,
        limit: int = 20,
        offset: int = 0
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT * FROM credit_transactions "
            "WHERE user_id = $1 "
            "ORDER BY created_at DESC "
            "LIMIT $2 OFFSET $3"
        )
        return await query(
            self._pool, 
            sql=sql, 
            params=[uuid.UUID(user_id), limit, offset]
        )
