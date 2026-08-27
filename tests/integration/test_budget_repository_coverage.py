"""Exercise the durable budget repository against PostgreSQL."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from uuid import uuid4

import pytest

from hevi.budget import BudgetError, BudgetExceeded, BudgetRepository


@pytest.mark.asyncio
async def test_budget_repository_lifecycle_is_idempotent_and_append_only(pool) -> None:
    production_id = uuid4()
    repository = BudgetRepository(pool)
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO productions (id, user_id, type, status) VALUES ($1, $2, $3, $4)",
                production_id,
                "budget-coverage-user",
                "budget-coverage",
                "draft",
            )
        with pytest.raises(BudgetError, match="hard_limit_must_be_positive"):
            await repository.ensure_envelope(production_id=production_id, hard_limit_usd=0)
        envelope = await repository.ensure_envelope(
            production_id=production_id,
            hard_limit_usd=20,
            soft_limit_usd=15,
            retake_pool_usd=2,
            stage_allocations={"rendering": 10, "audio_post": 4},
        )
        assert envelope.hard_limit_usd == Decimal("20")
        assert set(envelope.stages) == {"rendering", "audio_post"}
        again = await repository.ensure_envelope(
            production_id=production_id, hard_limit_usd=999, stage_allocations={"rendering": 1}
        )
        assert again.hard_limit_usd == Decimal("20")
        assert await repository.get(uuid4()) is None

        with pytest.raises(BudgetError, match="production_budget_not_configured"):
            await repository.check_available(production_id=uuid4(), amount_usd=1)
        available = await repository.check_available(
            production_id=production_id, amount_usd=2, stage_category="rendering"
        )
        assert available.amount_usd == Decimal("2")
        with pytest.raises(BudgetExceeded, match="stage_budget_exhausted"):
            await repository.check_available(
                production_id=production_id, amount_usd=11, stage_category="rendering"
            )

        first = await repository.reserve_attempt(
            production_id=production_id,
            attempt_key="render-1",
            estimated_cost_usd=3,
            stage_category="rendering",
            external_ref="render-1-ref",
        )
        duplicate = await repository.reserve_attempt(
            production_id=production_id,
            attempt_key="render-1",
            estimated_cost_usd=8,
            stage_category="rendering",
        )
        assert duplicate.attempt_id == first.attempt_id
        settled = await repository.settle_attempt(
            first.attempt_id, actual_cost_usd=2, provider_cost_ref="provider-2"
        )
        assert settled.status == "settled"
        assert (await repository.settle_attempt(first.attempt_id, actual_cost_usd=9)).status == "settled"
        refunded = await repository.refund_attempt(first.attempt_id, amount_usd=1, external_ref="refund-1")
        assert refunded.refunded_cost_usd == Decimal("1")
        with pytest.raises(BudgetError, match="refund_exceeds_attempt_spend"):
            await repository.refund_attempt(first.attempt_id, amount_usd=2)

        released = await repository.reserve_attempt(
            production_id=production_id,
            attempt_key="render-2",
            estimated_cost_usd=1,
            stage_category="audio_post",
        )
        assert (await repository.release_attempt(released.attempt_id)).status == "released"
        assert (await repository.release_attempt(released.attempt_id)).status == "released"
        with pytest.raises(BudgetError, match="budget_attempt_not_found"):
            await repository.release_attempt(uuid4())

        adjusted = await repository.adjust(
            production_id=production_id, delta_usd="0.50", external_ref="adj-1", reason="rounding"
        )
        assert adjusted.spent_usd == Decimal("1.50")
        with pytest.raises(BudgetError, match="adjustment_must_not_be_zero"):
            await repository.adjust(
                production_id=production_id, delta_usd=0, external_ref="adj-0", reason="invalid"
            )
        with pytest.raises(BudgetExceeded, match="invalid_budget_adjustment"):
            await repository.adjust(
                production_id=production_id, delta_usd=-99, external_ref="adj-bad", reason="invalid"
            )

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT entry_type, amount_usd FROM budget_ledger "
                "WHERE production_budget_id = (SELECT id FROM production_budgets WHERE production_id=$1) "
                "ORDER BY created_at, id",
                production_id,
            )
        assert Counter(row["entry_type"] for row in rows) == Counter(
            {
                "reserve": 2,
                "consume": 1,
                "release": 2,
                "refund": 1,
                "adjustment": 1,
            }
        )
        assert sorted(
            (row["entry_type"], Decimal(str(row["amount_usd"]))) for row in rows
        ) == sorted(
            [
                ("reserve", Decimal("3")),
                ("consume", Decimal("2")),
                ("release", Decimal("1")),
                ("refund", Decimal("1")),
                ("reserve", Decimal("1")),
                ("release", Decimal("1")),
                ("adjustment", Decimal("0.50")),
            ]
        )
    finally:
        async with pool.acquire() as conn:
            budget_id = await conn.fetchval(
                "SELECT id FROM production_budgets WHERE production_id=$1", production_id
            )
            if budget_id is not None:
                await conn.execute("ALTER TABLE budget_ledger DISABLE TRIGGER budget_ledger_append_only")
                await conn.execute("DELETE FROM budget_ledger WHERE production_budget_id=$1", budget_id)
                await conn.execute("ALTER TABLE budget_ledger ENABLE TRIGGER budget_ledger_append_only")
                await conn.execute("DELETE FROM budget_attempts WHERE production_budget_id=$1", budget_id)
                await conn.execute("DELETE FROM stage_budgets WHERE production_budget_id=$1", budget_id)
                await conn.execute("DELETE FROM production_budgets WHERE id=$1", budget_id)
            await conn.execute("DELETE FROM productions WHERE id=$1", production_id)
