from __future__ import annotations

from typing import Any

from hevi.credits.repository import CreditRepository


class AccountService:
    def __init__(self, repo: CreditRepository) -> None:
        self._repo = repo

    async def get_balance(self, user_id: str) -> int:
        account = await self._repo.get_or_create_account(user_id)
        return int(account.get("balance", 0))

    async def topup(
        self, user_id: str, amount: int, order_ref: str | None = None
    ) -> dict[str, Any]:
        if amount <= 0:
            raise ValueError("Topup amount must be positive")
        return await self._repo.update_balance_with_ledger(
            user_id=user_id, amount=amount, tx_type="topup", reference=order_ref
        )

    async def consume(
        self, user_id: str, amount: int, task_ref: str | None = None
    ) -> dict[str, Any]:
        if amount <= 0:
            raise ValueError("Consume amount must be positive")
        return await self._repo.update_balance_with_ledger(
            user_id=user_id, amount=-amount, tx_type="consume", reference=task_ref
        )

    async def refund(
        self, user_id: str, amount: int, task_ref: str | None = None
    ) -> dict[str, Any]:
        if amount <= 0:
            raise ValueError("Refund amount must be positive")
        return await self._repo.update_balance_with_ledger(
            user_id=user_id, amount=amount, tx_type="refund", reference=task_ref
        )

    async def refund_for_task(self, user_id: str, task_ref: str) -> dict[str, Any]:
        """Refund exactly what a task consumed — and only if it actually consumed.

        Avoids over-refunding: a task can be marked 'running' before consume()
        runs (crash window) or after a 0-credit local run, so blindly refunding
        credits_reserved would gift the user credits they never spent. We look up
        the consume ledger entry and refund its magnitude; the refund itself is
        idempotent via the (user, task_ref, 'refund') unique key.
        """
        consume_tx = await self._repo.get_transaction(user_id, task_ref, "consume")
        if consume_tx is None:
            return {"refunded": 0, "reason": "no_consume"}
        amount = abs(int(consume_tx["amount"]))
        if amount <= 0:
            return {"refunded": 0, "reason": "zero_consume"}
        result = await self._repo.update_balance_with_ledger(
            user_id=user_id, amount=amount, tx_type="refund", reference=task_ref
        )
        return {"refunded": amount, **result}

    async def list_transactions(
        self, user_id: str, limit: int = 20, offset: int = 0
    ) -> list[dict[str, Any]]:
        return await self._repo.list_transactions(user_id, limit, offset)
