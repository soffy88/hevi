"""Pure budget-envelope contracts and accounting rules.

The repository layer persists these state transitions.  Keeping the arithmetic
here makes the most important budget guarantees testable without a database:
hard production limits are never exceeded, stage borrowing is explicit, and a
retake cannot fall back to the ordinary rendering allocation.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Money = Decimal
LedgerEntryType = Literal["reserve", "consume", "release", "refund", "adjustment"]
BorrowPolicy = Literal["none", "production_remaining", "retake_pool_only"]


class BudgetError(ValueError):
    """Base class for budget policy and accounting failures."""


class BudgetExceeded(BudgetError):
    """A reservation or settlement would exceed an immutable budget boundary."""


def money(value: Decimal | float | int | str) -> Decimal:
    """Normalize monetary inputs without introducing binary-float rounding."""

    return value if isinstance(value, Decimal) else Decimal(str(value))


class StageBudget(BaseModel):
    category: str
    allocation_usd: Money = Field(ge=0)
    reserved_usd: Money = Field(default=Decimal("0"), ge=0)
    spent_usd: Money = Field(default=Decimal("0"), ge=0)
    borrow_policy: BorrowPolicy = "none"

    @property
    def remaining_usd(self) -> Money:
        return self.allocation_usd - self.reserved_usd - self.spent_usd


class BudgetDecision(BaseModel):
    allowed: bool
    reason: str = ""
    borrowed_usd: Money = Decimal("0")
    soft_limit_exceeded: bool = False


class BudgetReservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    attempt_id: uuid.UUID
    amount_usd: Money = Field(gt=0)
    stage_category: str
    is_retake: bool = False
    borrowed_usd: Money = Field(default=Decimal("0"), ge=0)
    soft_limit_exceeded: bool = False


class BudgetAttempt(BaseModel):
    """Durable provider attempt projection used for settlement and audit."""

    id: uuid.UUID
    production_budget_id: uuid.UUID
    task_id: uuid.UUID | None = None
    stage_category: str
    attempt_key: str
    estimated_cost_usd: Money = Decimal("0")
    reserved_cost_usd: Money = Decimal("0")
    actual_cost_usd: Money = Decimal("0")
    refunded_cost_usd: Money = Decimal("0")
    currency: str = "USD"
    provider_cost_ref: str | None = None
    is_retake: bool = False
    borrowed_usd: Money = Decimal("0")
    status: Literal["reserved", "settled", "released"] = "reserved"


class BudgetEnvelope(BaseModel):
    """Production-level budget and its stage allocations."""

    production_id: uuid.UUID
    hard_limit_usd: Money = Field(gt=0)
    soft_limit_usd: Money = Field(ge=0)
    reserved_usd: Money = Field(default=Decimal("0"), ge=0)
    spent_usd: Money = Field(default=Decimal("0"), ge=0)
    retake_pool_usd: Money = Field(default=Decimal("0"), ge=0)
    retake_reserved_usd: Money = Field(default=Decimal("0"), ge=0)
    retake_spent_usd: Money = Field(default=Decimal("0"), ge=0)
    version: int = Field(default=1, ge=1)
    stages: dict[str, StageBudget] = Field(default_factory=dict)

    @field_validator(
        "hard_limit_usd",
        "soft_limit_usd",
        "reserved_usd",
        "spent_usd",
        "retake_pool_usd",
        "retake_reserved_usd",
        "retake_spent_usd",
        mode="before",
    )
    @classmethod
    def _normalize_money(cls, value: Decimal | float | int | str) -> Decimal:
        return money(value)

    @property
    def remaining_usd(self) -> Money:
        return self.hard_limit_usd - self.reserved_usd - self.spent_usd

    @property
    def soft_remaining_usd(self) -> Money:
        return self.soft_limit_usd - self.reserved_usd - self.spent_usd

    @property
    def retake_remaining_usd(self) -> Money:
        return self.retake_pool_usd - self.retake_reserved_usd - self.retake_spent_usd

    def decision(
        self,
        *,
        amount_usd: Decimal | float | int | str,
        stage_category: str,
        is_retake: bool = False,
        allow_borrow: bool = False,
    ) -> BudgetDecision:
        amount = money(amount_usd)
        if amount <= 0:
            return BudgetDecision(allowed=False, reason="amount_must_be_positive")
        if self.remaining_usd < amount:
            return BudgetDecision(
                allowed=False,
                reason="production_hard_limit_exceeded",
            )

        if is_retake:
            # Retakes have a separate hard boundary.  In particular, available
            # rendering money is deliberately not considered here.
            if self.retake_remaining_usd < amount:
                return BudgetDecision(allowed=False, reason="retake_pool_exhausted")
            return BudgetDecision(
                allowed=True,
                borrowed_usd=Decimal("0"),
                soft_limit_exceeded=self.soft_remaining_usd < amount,
            )

        stage = self.stages.get(stage_category)
        if stage is None:
            return BudgetDecision(allowed=False, reason=f"unknown_stage:{stage_category}")
        stage_remaining = stage.remaining_usd
        if stage_remaining >= amount:
            borrowed = Decimal("0")
        elif allow_borrow and stage.borrow_policy == "production_remaining":
            borrowed = amount - max(stage_remaining, Decimal("0"))
        else:
            return BudgetDecision(
                allowed=False,
                reason=f"stage_budget_exhausted:{stage_category}",
            )
        return BudgetDecision(
            allowed=True,
            borrowed_usd=borrowed,
            soft_limit_exceeded=self.soft_remaining_usd < amount,
        )

    def reserve(
        self,
        *,
        attempt_id: uuid.UUID,
        amount_usd: Decimal | float | int | str,
        stage_category: str,
        is_retake: bool = False,
        allow_borrow: bool = False,
    ) -> tuple[BudgetEnvelope, BudgetReservation]:
        amount = money(amount_usd)
        decision = self.decision(
            amount_usd=amount,
            stage_category=stage_category,
            is_retake=is_retake,
            allow_borrow=allow_borrow,
        )
        if not decision.allowed:
            raise BudgetExceeded(decision.reason)

        updated = self.model_copy(deep=True)
        updated.reserved_usd += amount
        if is_retake:
            updated.retake_reserved_usd += amount
        else:
            updated.stages[stage_category].reserved_usd += amount
        return updated, BudgetReservation(
            attempt_id=attempt_id,
            amount_usd=amount,
            stage_category=stage_category,
            is_retake=is_retake,
            borrowed_usd=decision.borrowed_usd,
            soft_limit_exceeded=decision.soft_limit_exceeded,
        )

    def release(
        self,
        *,
        amount_usd: Decimal | float | int | str,
        stage_category: str,
        is_retake: bool = False,
    ) -> BudgetEnvelope:
        amount = money(amount_usd)
        updated = self.model_copy(deep=True)
        if amount <= 0:
            raise BudgetError("amount_must_be_positive")
        if updated.reserved_usd < amount:
            raise BudgetError("reservation_release_exceeds_reserved")
        updated.reserved_usd -= amount
        if is_retake:
            if updated.retake_reserved_usd < amount:
                raise BudgetError("retake_release_exceeds_reserved")
            updated.retake_reserved_usd -= amount
        else:
            stage = updated.stages.get(stage_category)
            if stage is None or stage.reserved_usd < amount:
                raise BudgetError("stage_release_exceeds_reserved")
            stage.reserved_usd -= amount
        return updated

    def settle(
        self,
        *,
        reserved_usd: Decimal | float | int | str,
        actual_usd: Decimal | float | int | str,
        stage_category: str,
        is_retake: bool = False,
    ) -> BudgetEnvelope:
        """Convert a reservation into spend and release any unused amount."""

        reserved = money(reserved_usd)
        actual = money(actual_usd)
        if reserved <= 0 or actual < 0:
            raise BudgetError("invalid_settlement_amount")
        if self.reserved_usd < reserved:
            raise BudgetError("settlement_exceeds_reserved")
        updated = self.model_copy(deep=True)
        updated.reserved_usd -= reserved
        updated.spent_usd += actual
        if is_retake:
            if updated.retake_reserved_usd < reserved:
                raise BudgetError("retake_settlement_exceeds_reserved")
            updated.retake_reserved_usd -= reserved
            updated.retake_spent_usd += actual
            if updated.retake_spent_usd > updated.retake_pool_usd:
                raise BudgetExceeded("retake_pool_exhausted_at_settlement")
        else:
            stage = updated.stages.get(stage_category)
            if stage is None or stage.reserved_usd < reserved:
                raise BudgetError("stage_settlement_exceeds_reserved")
            stage.reserved_usd -= reserved
            stage.spent_usd += actual
        if updated.spent_usd + updated.reserved_usd > updated.hard_limit_usd:
            raise BudgetExceeded("production_hard_limit_exceeded_at_settlement")
        return updated

    def refund(
        self,
        *,
        amount_usd: Decimal | float | int | str,
        stage_category: str,
        is_retake: bool = False,
    ) -> BudgetEnvelope:
        amount = money(amount_usd)
        if amount <= 0:
            raise BudgetError("amount_must_be_positive")
        updated = self.model_copy(deep=True)
        if updated.spent_usd < amount:
            raise BudgetError("refund_exceeds_spent")
        updated.spent_usd -= amount
        if is_retake:
            if updated.retake_spent_usd < amount:
                raise BudgetError("retake_refund_exceeds_spent")
            updated.retake_spent_usd -= amount
        else:
            stage = updated.stages.get(stage_category)
            if stage is None or stage.spent_usd < amount:
                raise BudgetError("stage_refund_exceeds_spent")
            stage.spent_usd -= amount
        return updated


class BudgetLedgerEntry(BaseModel):
    """An append-only accounting entry."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    production_budget_id: uuid.UUID
    entry_type: LedgerEntryType
    # Adjustment entries may be negative; all reservation/consume/release/
    # refund entries are positive by repository policy.
    amount_usd: Money
    attempt_id: uuid.UUID | None = None
    stage_category: str | None = None
    external_ref: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


__all__ = [
    "BudgetAttempt",
    "BudgetDecision",
    "BudgetEnvelope",
    "BudgetError",
    "BudgetExceeded",
    "BudgetLedgerEntry",
    "BudgetReservation",
    "StageBudget",
    "money",
]
