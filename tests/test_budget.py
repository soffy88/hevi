from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from hevi.budget import (
    BudgetEnvelope,
    BudgetExceeded,
    BudgetLedgerEntry,
    StageBudget,
)


def envelope() -> BudgetEnvelope:
    return BudgetEnvelope(
        production_id=uuid4(),
        hard_limit_usd=100,
        soft_limit_usd=90,
        retake_pool_usd=10,
        stages={
            "rendering": StageBudget(category="rendering", allocation_usd=55),
            "audio_post": StageBudget(category="audio_post", allocation_usd=10),
        },
    )


def test_reservation_and_settlement_release_unused_amount() -> None:
    budget = envelope()
    budget, reservation = budget.reserve(
        attempt_id=uuid4(), amount_usd=20, stage_category="rendering"
    )
    assert budget.reserved_usd == Decimal("20")
    assert budget.stages["rendering"].reserved_usd == Decimal("20")

    budget = budget.settle(
        reserved_usd=reservation.amount_usd,
        actual_usd=12.5,
        stage_category="rendering",
    )
    assert budget.reserved_usd == Decimal("0")
    assert budget.spent_usd == Decimal("12.5")
    assert budget.stages["rendering"].spent_usd == Decimal("12.5")
    assert budget.remaining_usd == Decimal("87.5")


def test_stage_borrow_is_explicit_and_reported() -> None:
    budget = envelope()
    budget.stages["rendering"].borrow_policy = "production_remaining"
    with pytest.raises(BudgetExceeded, match="stage_budget_exhausted"):
        budget.reserve(
            attempt_id=uuid4(),
            amount_usd=60,
            stage_category="rendering",
            allow_borrow=False,
        )

    budget, reservation = budget.reserve(
        attempt_id=uuid4(),
        amount_usd=60,
        stage_category="rendering",
        allow_borrow=True,
    )
    assert reservation.borrowed_usd == Decimal("5")
    assert budget.stages["rendering"].remaining_usd == Decimal("-5")


def test_retake_never_consumes_rendering_budget() -> None:
    budget = envelope()
    budget, _ = budget.reserve(
        attempt_id=uuid4(), amount_usd=55, stage_category="rendering"
    )
    budget, _ = budget.reserve(
        attempt_id=uuid4(), amount_usd=10, stage_category="retake", is_retake=True
    )
    assert budget.retake_remaining_usd == Decimal("0")
    assert budget.stages["rendering"].reserved_usd == Decimal("55")
    with pytest.raises(BudgetExceeded, match="retake_pool_exhausted"):
        budget.reserve(
            attempt_id=uuid4(), amount_usd=0.01, stage_category="retake", is_retake=True
        )


def test_ledger_entries_are_immutable_models() -> None:
    entry = BudgetLedgerEntry(
        id=uuid4(),
        production_budget_id=uuid4(),
        entry_type="adjustment",
        amount_usd=Decimal("-1.25"),
    )
    with pytest.raises(ValidationError):
        entry.amount_usd = Decimal("0")
