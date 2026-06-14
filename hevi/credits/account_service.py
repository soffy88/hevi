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

    async def list_transactions(
        self, user_id: str, limit: int = 20, offset: int = 0
    ) -> list[dict[str, Any]]:
        return await self._repo.list_transactions(user_id, limit, offset)
