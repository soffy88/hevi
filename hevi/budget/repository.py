"""Transactional PostgreSQL repository for budget envelopes.

Every balance mutation locks the production envelope first and appends a ledger
row in the same transaction.  The ledger is intentionally never updated by
this repository; corrections are represented by a new ``adjustment`` entry.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from obase.persistence import PgPool

from .models import (
    BudgetAttempt,
    BudgetEnvelope,
    BudgetError,
    BudgetExceeded,
    BudgetReservation,
    StageBudget,
    money,
)

DEFAULT_STAGE_RATIOS: dict[str, Decimal] = {
    "preproduction": Decimal("0.05"),
    "asset_build": Decimal("0.20"),
    "rendering": Decimal("0.55"),
    "audio_post": Decimal("0.10"),
}


def _uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _attempt_id(production_id: uuid.UUID, attempt_key: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"hevi:budget-attempt:{production_id}:{attempt_key}")


def _decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))


class BudgetRepository:
    def __init__(self, pool: PgPool) -> None:
        self.pool = pool

    async def ensure_envelope(
        self,
        *,
        production_id: str | uuid.UUID,
        hard_limit_usd: Decimal | float | int | str,
        soft_limit_usd: Decimal | float | int | str | None = None,
        retake_pool_usd: Decimal | float | int | str | None = None,
        stage_allocations: dict[str, Decimal | float | int | str] | None = None,
    ) -> BudgetEnvelope:
        """Create a production envelope once; repeated calls are idempotent."""

        pid = _uuid(production_id)
        hard = money(hard_limit_usd)
        if hard <= 0:
            raise BudgetError("hard_limit_must_be_positive")
        retake = money(retake_pool_usd) if retake_pool_usd is not None else hard * Decimal("0.10")
        soft = money(soft_limit_usd) if soft_limit_usd is not None else hard * Decimal("0.90")
        allocations = {
            category: money(hard * ratio)
            for category, ratio in DEFAULT_STAGE_RATIOS.items()
        }
        if stage_allocations is not None:
            allocations = {category: money(value) for category, value in stage_allocations.items()}
        if retake < 0 or sum(allocations.values(), Decimal("0")) + retake > hard:
            raise BudgetError("stage_and_retake_allocations_exceed_hard_limit")

        now = datetime.now(UTC).replace(tzinfo=None)
        async with self.pool.acquire() as conn, conn.transaction():
            existing = await conn.fetchrow(
                "SELECT id FROM production_budgets WHERE production_id = $1 FOR UPDATE", pid
            )
            if existing is None:
                budget_id = uuid.uuid4()
                await conn.execute(
                    """
                    INSERT INTO production_budgets
                        (id, production_id, hard_limit_usd, soft_limit_usd,
                         retake_pool_usd, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $6)
                    """,
                    budget_id,
                    pid,
                    hard,
                    soft,
                    retake,
                    now,
                )
                for category, allocation in allocations.items():
                    await conn.execute(
                        """
                        INSERT INTO stage_budgets
                            (id, production_budget_id, category, allocation_usd, borrow_policy)
                        VALUES ($1, $2, $3, $4, $5)
                        """,
                        uuid.uuid4(),
                        budget_id,
                        category,
                        allocation,
                        "none",
                    )
            else:
                budget_id = existing["id"]
        envelope = await self.get(pid)
        if envelope is None:
            raise BudgetError("budget_envelope_not_found_after_create")
        return envelope

    async def get(self, production_id: str | uuid.UUID) -> BudgetEnvelope | None:
        pid = _uuid(production_id)
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM production_budgets WHERE production_id = $1", pid
            )
            if row is None:
                return None
            stages = await conn.fetch(
                """
                SELECT category, allocation_usd, reserved_usd, spent_usd, borrow_policy
                FROM stage_budgets WHERE production_budget_id = $1 ORDER BY category
                """,
                row["id"],
            )
        return self._envelope_from_rows(row, stages)

    @staticmethod
    def _envelope_from_rows(row: Any, stages: Any) -> BudgetEnvelope:
        return BudgetEnvelope(
            production_id=row["production_id"],
            hard_limit_usd=_decimal(row["hard_limit_usd"]),
            soft_limit_usd=_decimal(row["soft_limit_usd"]),
            reserved_usd=_decimal(row["reserved_usd"]),
            spent_usd=_decimal(row["spent_usd"]),
            retake_pool_usd=_decimal(row["retake_pool_usd"]),
            retake_reserved_usd=_decimal(row["retake_reserved_usd"]),
            retake_spent_usd=_decimal(row["retake_spent_usd"]),
            version=int(row["version"]),
            stages={
                str(stage["category"]): StageBudget(
                    category=str(stage["category"]),
                    allocation_usd=_decimal(stage["allocation_usd"]),
                    reserved_usd=_decimal(stage["reserved_usd"]),
                    spent_usd=_decimal(stage["spent_usd"]),
                    borrow_policy=cast(
                        Any, str(stage["borrow_policy"] or "none")
                    ),
                )
                for stage in stages
            },
        )

    async def check_available(
        self,
        *,
        production_id: str | uuid.UUID,
        amount_usd: Decimal | float | int | str,
        stage_category: str = "rendering",
        is_retake: bool = False,
        allow_borrow: bool = False,
    ) -> BudgetReservation:
        """Check the envelope without changing it.

        This is useful for schedulers and API previews; actual task admission
        should use :meth:`reserve_attempt` to avoid a check-then-race.
        """

        envelope = await self.get(production_id)
        if envelope is None:
            raise BudgetError("production_budget_not_configured")
        decision = envelope.decision(
            amount_usd=amount_usd,
            stage_category=stage_category,
            is_retake=is_retake,
            allow_borrow=allow_borrow,
        )
        if not decision.allowed:
            raise BudgetExceeded(decision.reason)
        return BudgetReservation(
            attempt_id=uuid.uuid4(),
            amount_usd=money(amount_usd),
            stage_category=stage_category,
            is_retake=is_retake,
            borrowed_usd=decision.borrowed_usd,
            soft_limit_exceeded=decision.soft_limit_exceeded,
        )

    async def reserve_attempt(
        self,
        *,
        production_id: str | uuid.UUID,
        attempt_key: str,
        estimated_cost_usd: Decimal | float | int | str,
        stage_category: str = "rendering",
        is_retake: bool = False,
        allow_borrow: bool = False,
        task_id: str | uuid.UUID | None = None,
        currency: str = "USD",
        external_ref: str | None = None,
    ) -> BudgetReservation:
        """Atomically reserve production, stage, and (optionally) retake funds."""

        pid = _uuid(production_id)
        attempt_id = _attempt_id(pid, attempt_key)
        amount = money(estimated_cost_usd)
        task_uuid = _uuid(task_id) if task_id is not None else None
        now = datetime.now(UTC).replace(tzinfo=None)
        async with self.pool.acquire() as conn, conn.transaction():
            # Serialize all reservations for one production before looking up
            # the deterministic attempt key.  If the key lookup happens first,
            # two concurrent callers can both observe "missing" and race into
            # the same UUID primary key despite the unique attempt_key.
            budget_row = await conn.fetchrow(
                "SELECT * FROM production_budgets WHERE production_id = $1 FOR UPDATE",
                pid,
            )
            if budget_row is None:
                raise BudgetError("production_budget_not_configured")
            existing = await conn.fetchrow(
                """
                SELECT reserved_cost_usd, stage_category, is_retake, borrowed_usd, status
                FROM budget_attempts
                WHERE production_budget_id = $1
                  AND attempt_key = $2
                FOR UPDATE
                """,
                budget_row["id"],
                attempt_key,
            )
            if existing is not None:
                if str(existing["status"]) != "reserved":
                    raise BudgetError(f"attempt_not_reservable:{attempt_key}")
                return BudgetReservation(
                    attempt_id=attempt_id,
                    amount_usd=_decimal(existing["reserved_cost_usd"]),
                    stage_category=str(existing["stage_category"]),
                    is_retake=bool(existing["is_retake"]),
                    borrowed_usd=_decimal(existing["borrowed_usd"]),
                )

            stage_rows = await conn.fetch(
                """
                SELECT category, allocation_usd, reserved_usd, spent_usd, borrow_policy
                FROM stage_budgets WHERE production_budget_id = $1
                """,
                budget_row["id"],
            )
            envelope = self._envelope_from_rows(budget_row, stage_rows)
            updated, reservation = envelope.reserve(
                attempt_id=attempt_id,
                amount_usd=amount,
                stage_category=stage_category,
                is_retake=is_retake,
                allow_borrow=allow_borrow,
            )
            await self._update_balances(conn, budget_row["id"], updated, stage_category, is_retake)
            await conn.execute(
                """
                INSERT INTO budget_attempts
                    (id, production_budget_id, task_id, stage_category, attempt_key,
                     estimated_cost_usd, reserved_cost_usd, currency, is_retake,
                     borrowed_usd, status, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $6, $7, $8, $9, 'reserved', $10, $10)
                """,
                attempt_id,
                budget_row["id"],
                task_uuid,
                stage_category,
                attempt_key,
                amount,
                currency,
                is_retake,
                reservation.borrowed_usd,
                now,
            )
            await self._append_ledger(
                conn,
                production_budget_id=budget_row["id"],
                entry_type="reserve",
                amount=amount,
                attempt_id=attempt_id,
                stage_category=stage_category,
                external_ref=external_ref or attempt_key,
                metadata={"is_retake": is_retake, "borrowed_usd": str(reservation.borrowed_usd)},
                created_at=now,
            )
        return reservation

    async def attach_task(self, attempt_id: str | uuid.UUID, task_id: str | uuid.UUID) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE budget_attempts SET task_id = $2, updated_at = NOW() WHERE id = $1",
                _uuid(attempt_id),
                _uuid(task_id),
            )
        return str(result).endswith("1")

    async def settle_attempt(
        self,
        attempt_id: str | uuid.UUID,
        *,
        actual_cost_usd: Decimal | float | int | str,
        provider_cost_ref: str | None = None,
        external_ref: str | None = None,
    ) -> BudgetAttempt:
        """Consume actual cost and release unused reservation atomically."""

        aid = _uuid(attempt_id)
        actual = money(actual_cost_usd)
        now = datetime.now(UTC).replace(tzinfo=None)
        async with self.pool.acquire() as conn, conn.transaction():
            attempt = await conn.fetchrow(
                "SELECT * FROM budget_attempts WHERE id = $1 FOR UPDATE", aid
            )
            if attempt is None:
                raise BudgetError("budget_attempt_not_found")
            if str(attempt["status"]) != "reserved":
                return self._attempt_from_row(attempt)
            budget_row = await conn.fetchrow(
                "SELECT * FROM production_budgets WHERE id = $1 FOR UPDATE",
                attempt["production_budget_id"],
            )
            if budget_row is None:
                raise BudgetError("production_budget_not_found")
            stage_rows = await conn.fetch(
                "SELECT category, allocation_usd, reserved_usd, spent_usd, borrow_policy "
                "FROM stage_budgets WHERE production_budget_id = $1",
                budget_row["id"],
            )
            reserved = _decimal(attempt["reserved_cost_usd"])
            stage_category = str(attempt["stage_category"])
            is_retake = bool(attempt["is_retake"])
            envelope = self._envelope_from_rows(budget_row, stage_rows)
            updated = envelope.settle(
                reserved_usd=reserved,
                actual_usd=actual,
                stage_category=stage_category,
                is_retake=is_retake,
            )
            await self._update_balances(conn, budget_row["id"], updated, stage_category, is_retake)
            await conn.execute(
                """
                UPDATE budget_attempts
                SET reserved_cost_usd = 0, actual_cost_usd = $2,
                    provider_cost_ref = COALESCE($3, provider_cost_ref),
                    status = 'settled', updated_at = $4
                WHERE id = $1
                """,
                aid,
                actual,
                provider_cost_ref,
                now,
            )
            if actual > 0:
                await self._append_ledger(
                    conn,
                    production_budget_id=budget_row["id"],
                    entry_type="consume",
                    amount=actual,
                    attempt_id=aid,
                    stage_category=stage_category,
                    external_ref=external_ref or provider_cost_ref,
                    metadata={"reserved_usd": str(reserved)},
                    created_at=now,
                )
            if reserved > actual:
                await self._append_ledger(
                    conn,
                    production_budget_id=budget_row["id"],
                    entry_type="release",
                    amount=reserved - actual,
                    attempt_id=aid,
                    stage_category=stage_category,
                    external_ref=external_ref or f"{aid}:release",
                    metadata={},
                    created_at=now,
                )
            updated_attempt = await conn.fetchrow(
                "SELECT * FROM budget_attempts WHERE id = $1", aid
            )
        return self._attempt_from_row(updated_attempt)

    async def release_attempt(
        self,
        attempt_id: str | uuid.UUID,
        *,
        external_ref: str | None = None,
    ) -> BudgetAttempt:
        aid = _uuid(attempt_id)
        now = datetime.now(UTC).replace(tzinfo=None)
        async with self.pool.acquire() as conn, conn.transaction():
            attempt = await conn.fetchrow(
                "SELECT * FROM budget_attempts WHERE id = $1 FOR UPDATE", aid
            )
            if attempt is None:
                raise BudgetError("budget_attempt_not_found")
            if str(attempt["status"]) != "reserved":
                return self._attempt_from_row(attempt)
            budget_row = await conn.fetchrow(
                "SELECT * FROM production_budgets WHERE id = $1 FOR UPDATE",
                attempt["production_budget_id"],
            )
            stage_rows = await conn.fetch(
                "SELECT category, allocation_usd, reserved_usd, spent_usd, borrow_policy "
                "FROM stage_budgets WHERE production_budget_id = $1",
                budget_row["id"],
            )
            amount = _decimal(attempt["reserved_cost_usd"])
            stage_category = str(attempt["stage_category"])
            is_retake = bool(attempt["is_retake"])
            envelope = self._envelope_from_rows(budget_row, stage_rows)
            updated = envelope.release(
                amount_usd=amount,
                stage_category=stage_category,
                is_retake=is_retake,
            )
            await self._update_balances(conn, budget_row["id"], updated, stage_category, is_retake)
            await conn.execute(
                "UPDATE budget_attempts SET reserved_cost_usd = 0, "
                "status = 'released', updated_at = $2 WHERE id = $1",
                aid,
                now,
            )
            await self._append_ledger(
                conn,
                production_budget_id=budget_row["id"],
                entry_type="release",
                amount=amount,
                attempt_id=aid,
                stage_category=stage_category,
                external_ref=external_ref or f"{aid}:release",
                metadata={},
                created_at=now,
            )
            updated_attempt = await conn.fetchrow(
                "SELECT * FROM budget_attempts WHERE id = $1", aid
            )
        return self._attempt_from_row(updated_attempt)

    async def refund_attempt(
        self,
        attempt_id: str | uuid.UUID,
        *,
        amount_usd: Decimal | float | int | str,
        external_ref: str | None = None,
    ) -> BudgetAttempt:
        """Refund spent money through a new ledger entry, never by rewriting history."""

        aid = _uuid(attempt_id)
        amount = money(amount_usd)
        now = datetime.now(UTC).replace(tzinfo=None)
        async with self.pool.acquire() as conn, conn.transaction():
            attempt = await conn.fetchrow(
                "SELECT * FROM budget_attempts WHERE id = $1 FOR UPDATE", aid
            )
            if attempt is None:
                raise BudgetError("budget_attempt_not_found")
            remaining_refundable = _decimal(attempt["actual_cost_usd"]) - _decimal(
                attempt["refunded_cost_usd"]
            )
            if remaining_refundable < amount:
                raise BudgetError("refund_exceeds_attempt_spend")
            budget_row = await conn.fetchrow(
                "SELECT * FROM production_budgets WHERE id = $1 FOR UPDATE",
                attempt["production_budget_id"],
            )
            stage_rows = await conn.fetch(
                "SELECT category, allocation_usd, reserved_usd, spent_usd, borrow_policy "
                "FROM stage_budgets WHERE production_budget_id = $1",
                budget_row["id"],
            )
            stage_category = str(attempt["stage_category"])
            is_retake = bool(attempt["is_retake"])
            envelope = self._envelope_from_rows(budget_row, stage_rows)
            updated = envelope.refund(
                amount_usd=amount,
                stage_category=stage_category,
                is_retake=is_retake,
            )
            await self._update_balances(conn, budget_row["id"], updated, stage_category, is_retake)
            await conn.execute(
                "UPDATE budget_attempts SET refunded_cost_usd = refunded_cost_usd + $2, "
                "updated_at = $3 WHERE id = $1",
                aid,
                amount,
                now,
            )
            await self._append_ledger(
                conn,
                production_budget_id=budget_row["id"],
                entry_type="refund",
                amount=amount,
                attempt_id=aid,
                stage_category=stage_category,
                external_ref=external_ref or f"{aid}:refund",
                metadata={},
                created_at=now,
            )
            updated_attempt = await conn.fetchrow(
                "SELECT * FROM budget_attempts WHERE id = $1", aid
            )
        return self._attempt_from_row(updated_attempt)

    async def adjust(
        self,
        *,
        production_id: str | uuid.UUID,
        delta_usd: Decimal | float | int | str,
        external_ref: str,
        reason: str,
    ) -> BudgetEnvelope:
        """Apply an explicit administrative correction with an audit entry."""

        pid = _uuid(production_id)
        delta = money(delta_usd)
        if delta == 0:
            raise BudgetError("adjustment_must_not_be_zero")
        now = datetime.now(UTC).replace(tzinfo=None)
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM production_budgets WHERE production_id = $1 FOR UPDATE", pid
            )
            if row is None:
                raise BudgetError("production_budget_not_configured")
            stages = await conn.fetch(
                "SELECT category, allocation_usd, reserved_usd, spent_usd, borrow_policy "
                "FROM stage_budgets WHERE production_budget_id = $1",
                row["id"],
            )
            envelope = self._envelope_from_rows(row, stages)
            updated = envelope.model_copy(deep=True)
            updated.spent_usd += delta
            if updated.spent_usd < 0 or (
                updated.spent_usd + updated.reserved_usd > updated.hard_limit_usd
            ):
                raise BudgetExceeded("invalid_budget_adjustment")
            await conn.execute(
                "UPDATE production_budgets SET spent_usd = $2, version = version + 1, "
                "updated_at = $3 WHERE id = $1",
                row["id"],
                updated.spent_usd,
                now,
            )
            await self._append_ledger(
                conn,
                production_budget_id=row["id"],
                entry_type="adjustment",
                amount=delta,
                attempt_id=None,
                stage_category=None,
                external_ref=external_ref,
                metadata={"reason": reason},
                created_at=now,
            )
        return await self.get(pid)  # type: ignore[return-value]

    @staticmethod
    async def _update_balances(
        conn: Any,
        budget_id: uuid.UUID,
        envelope: BudgetEnvelope,
        stage_category: str,
        is_retake: bool,
    ) -> None:
        await conn.execute(
            """
            UPDATE production_budgets
            SET reserved_usd = $2, spent_usd = $3,
                retake_reserved_usd = $4, retake_spent_usd = $5,
                version = version + 1, updated_at = NOW()
            WHERE id = $1
            """,
            budget_id,
            envelope.reserved_usd,
            envelope.spent_usd,
            envelope.retake_reserved_usd,
            envelope.retake_spent_usd,
        )
        stage = envelope.stages.get(stage_category)
        if not is_retake and stage is not None:
            await conn.execute(
                "UPDATE stage_budgets SET reserved_usd = $2, spent_usd = $3, updated_at = NOW() "
                "WHERE production_budget_id = $1 AND category = $4",
                budget_id,
                stage.reserved_usd,
                stage.spent_usd,
                stage_category,
            )

    @staticmethod
    async def _append_ledger(
        conn: Any,
        *,
        production_budget_id: uuid.UUID,
        entry_type: str,
        amount: Decimal,
        attempt_id: uuid.UUID | None,
        stage_category: str | None,
        external_ref: str | None,
        metadata: dict[str, object],
        created_at: datetime,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO budget_ledger
                (id, production_budget_id, attempt_id, stage_category,
                 entry_type, amount_usd, external_ref, metadata_json, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            uuid.uuid4(),
            production_budget_id,
            attempt_id,
            stage_category,
            entry_type,
            amount,
            external_ref,
            metadata,
            created_at,
        )

    @staticmethod
    def _attempt_from_row(row: Any) -> BudgetAttempt:
        return BudgetAttempt(
            id=row["id"],
            production_budget_id=row["production_budget_id"],
            task_id=row["task_id"],
            stage_category=str(row["stage_category"]),
            attempt_key=str(row["attempt_key"]),
            estimated_cost_usd=_decimal(row["estimated_cost_usd"]),
            reserved_cost_usd=_decimal(row["reserved_cost_usd"]),
            actual_cost_usd=_decimal(row["actual_cost_usd"]),
            refunded_cost_usd=_decimal(row["refunded_cost_usd"]),
            currency=str(row["currency"]),
            provider_cost_ref=row["provider_cost_ref"],
            is_retake=bool(row["is_retake"]),
            borrowed_usd=_decimal(row["borrowed_usd"]),
            status=cast(Any, str(row["status"])),
        )


__all__ = ["DEFAULT_STAGE_RATIOS", "BudgetRepository"]
