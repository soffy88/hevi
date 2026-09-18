"""Production plan projection + pre-submit admission (Gap Closure W7).

K02/E04/E06/E09 without a second plan authority: :func:`project_plan`
is a pure projection over caller-supplied production state — graph node
facts, W2 currency evaluations, W1 presentation selection, provider
capability snapshots. It stores nothing; calling it twice over the same
inputs yields the same plan (PLAN_PROJECTION_SINGLE_SOURCE).

Per target the plan reports one of completed / ready / blocked / stale /
missing, plus next_actions and repair_actions. Blocked entries always
carry an actionable blocking_reason and a valid repair action.

Admission runs before submit, never after failure:

- single admission: ADMIT / CONFIRM (user decision, e.g. cost tier) /
  BLOCKED, reusing the W5 capability matcher;
- batch admission (E06): all-or-none — one blocked item blocks the whole
  batch with zero items admitted; confirms aggregate for one decision;
- provider rejections (E09) normalize to desensitized codes with an
  explicit retryable flag; credential-looking content is stripped.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hevi.creative.layer4.currency import ArtifactCurrency
from hevi.creative.layer4.endpoint_lifecycle import (
    AdmissionVerdict,
    CapabilityRequirement,
    DeclarativeEndpointDefinition,
    check_capability,
)
from hevi.creative.layer4.usage_ledger import redact_secrets


class PlanError(ValueError):
    """Refusal with a stable machine code."""


class TargetStatus(StrEnum):
    COMPLETED = "completed"
    READY = "ready"
    BLOCKED = "blocked"
    STALE = "stale"
    MISSING = "missing"


class RepairKind(StrEnum):
    RETRY_TARGET = "retry_target"
    REPLAN = "replan"
    FIX_REFERENCES = "fix_references"
    REGENERATE_EXPLICIT = "regenerate_explicit"
    RESTORE_ASSET = "restore_asset"
    SWITCH_PROVIDER = "switch_provider"
    CONFIRM_AND_PROCEED = "confirm_and_proceed"


class RepairAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str = Field(min_length=1)
    kind: RepairKind
    target_id: str = Field(min_length=1)
    detail: str = ""
    requires_confirmation: bool = False


class TargetPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_id: str = Field(min_length=1)
    status: TargetStatus
    blocking_reason: str | None = None
    repair_actions: tuple[RepairAction, ...] = ()
    next_actions: tuple[str, ...] = ()
    currency: ArtifactCurrency | None = None
    detail: str = ""

    @model_validator(mode="after")
    def _blocked_is_actionable(self) -> TargetPlan:
        if self.status is TargetStatus.BLOCKED:
            if not self.blocking_reason:
                raise PlanError("PLAN_BLOCKED_NEEDS_REASON")
            if not self.repair_actions:
                raise PlanError("PLAN_BLOCKED_NEEDS_REPAIR_ACTION")
        if self.status is not TargetStatus.BLOCKED and self.blocking_reason:
            raise PlanError("PLAN_ONLY_BLOCKED_CARRIES_BLOCKING_REASON")
        return self


class TargetFact(BaseModel):
    """Caller-projected production truth for one target. Input, not storage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_id: str = Field(min_length=1)
    required: bool = True
    verified_complete: bool = False
    currency: ArtifactCurrency | None = None
    basis_readable: bool = True
    blocking_reason: str | None = None
    repair_actions: tuple[RepairAction, ...] = ()


_REPAIR_FOR_REASON: dict[str, RepairKind] = {
    "unreadable basis": RepairKind.RESTORE_ASSET,
    "missing reference": RepairKind.FIX_REFERENCES,
    "capability": RepairKind.SWITCH_PROVIDER,
    "provider failure": RepairKind.RETRY_TARGET,
    "stale input": RepairKind.REGENERATE_EXPLICIT,
}


def validate_repair_action(action: RepairAction, known_target_ids: tuple[str, ...]) -> RepairAction:
    """REPAIR_ACTION_VALID: actions must name a real target with a coherent kind."""

    if action.target_id not in known_target_ids:
        raise PlanError(f"PLAN_REPAIR_UNKNOWN_TARGET:{action.target_id}")
    return action


def derive_repair_for_reason(reason: str, target_id: str) -> RepairAction:
    lowered = reason.lower()
    for marker, kind in _REPAIR_FOR_REASON.items():
        if marker in lowered:
            return RepairAction(
                action_id=f"repair-{target_id}-{kind.value}",
                kind=kind,
                target_id=target_id,
                detail=reason,
                requires_confirmation=kind is RepairKind.REGENERATE_EXPLICIT,
            )
    return RepairAction(
        action_id=f"repair-{target_id}-replan",
        kind=RepairKind.REPLAN,
        target_id=target_id,
        detail=reason,
    )


def derive_target_status(fact: TargetFact) -> TargetStatus:
    if not fact.basis_readable:
        return TargetStatus.BLOCKED
    if fact.blocking_reason:
        return TargetStatus.BLOCKED
    if fact.currency is ArtifactCurrency.BLOCKED:
        return TargetStatus.BLOCKED
    if fact.verified_complete:
        return TargetStatus.COMPLETED
    if fact.currency is ArtifactCurrency.STALE:
        return TargetStatus.STALE
    if fact.currency is ArtifactCurrency.MISSING or fact.currency is None:
        return TargetStatus.MISSING if fact.required else TargetStatus.READY
    return TargetStatus.READY


def project_plan(facts: tuple[TargetFact, ...]) -> tuple[TargetPlan, ...]:
    """Project an ordered plan. Pure: no stored fact state, no second authority."""

    plans: list[TargetPlan] = []
    for fact in facts:
        status = derive_target_status(fact)
        repair_actions = tuple(fact.repair_actions)
        blocking_reason = fact.blocking_reason
        if status is TargetStatus.BLOCKED:
            if blocking_reason is None:
                blocking_reason = "unreadable basis" if not fact.basis_readable else "blocked"
            if not repair_actions and blocking_reason is not None:
                repair_actions = (derive_repair_for_reason(blocking_reason, fact.target_id),)
        next_actions: tuple[str, ...] = ()
        if status is TargetStatus.READY:
            next_actions = (f"generate:{fact.target_id}",)
        elif status is TargetStatus.STALE:
            next_actions = (f"reuse-or-regenerate:{fact.target_id}",)
        elif status is TargetStatus.MISSING:
            next_actions = (f"generate:{fact.target_id}",)
        elif status is TargetStatus.COMPLETED:
            next_actions = ()
        else:
            next_actions = tuple(f"repair:{action.action_id}" for action in repair_actions)
        plans.append(
            TargetPlan(
                target_id=fact.target_id,
                status=status,
                blocking_reason=blocking_reason,
                repair_actions=tuple(
                    validate_repair_action(action, tuple(f.target_id for f in facts))
                    for action in repair_actions
                ),
                next_actions=next_actions,
                currency=fact.currency,
            )
        )
    return tuple(plans)


class AdmissionVerdict3(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: str
    reasons: tuple[str, ...] = ()
    admitted_items: tuple[str, ...] = ()


def admit_single(
    definition: DeclarativeEndpointDefinition,
    requirement: CapabilityRequirement,
    *,
    estimated_cost: float = 0.0,
    confirm_above_cost: float = 0.0,
    item_id: str = "item",
) -> AdmissionVerdict3:
    """Pre-submit single admission reusing the W5 capability matcher."""

    verdict: AdmissionVerdict = check_capability(definition, requirement)
    if not verdict.admitted:
        return AdmissionVerdict3(decision="blocked", reasons=verdict.reasons, admitted_items=())
    if confirm_above_cost > 0 and estimated_cost >= confirm_above_cost:
        return AdmissionVerdict3(
            decision="confirm",
            reasons=(
                f"estimated {estimated_cost} at/above confirm threshold {confirm_above_cost}",
            ),
            admitted_items=(item_id,),
        )
    return AdmissionVerdict3(decision="admit", reasons=(), admitted_items=(item_id,))


def admit_batch(
    items: tuple[tuple[str, DeclarativeEndpointDefinition, CapabilityRequirement, float], ...],
    *,
    confirm_above_cost: float = 0.0,
) -> AdmissionVerdict3:
    """All-or-none batch admission: one blocked item blocks the whole batch."""

    blocked_reasons: list[str] = []
    confirms: list[str] = []
    admitted: list[str] = []
    for item_id, definition, requirement, estimated_cost in items:
        verdict = admit_single(
            definition,
            requirement,
            estimated_cost=estimated_cost,
            confirm_above_cost=confirm_above_cost,
            item_id=item_id,
        )
        if verdict.decision == "blocked":
            blocked_reasons.extend(f"{item_id}: {reason}" for reason in verdict.reasons)
        elif verdict.decision == "confirm":
            confirms.append(item_id)
        else:
            admitted.append(item_id)
    if blocked_reasons:
        return AdmissionVerdict3(
            decision="blocked", reasons=tuple(blocked_reasons), admitted_items=()
        )
    if confirms:
        return AdmissionVerdict3(
            decision="confirm",
            reasons=(f"awaiting user decision for: {', '.join(confirms)}",),
            admitted_items=tuple(confirms),
        )
    return AdmissionVerdict3(decision="admit", reasons=(), admitted_items=tuple(admitted))


class NormalizedRejection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_code: str | None = None
    normalized_code: str
    safe_message: str
    retryable: bool
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


_RETRYABLE_CODES = {"RATE_LIMITED", "TIMEOUT", "SERVER_ERROR", "UNAVAILABLE"}


def normalize_rejection(
    *, provider_code: str | None, message: str, normalized_code: str
) -> NormalizedRejection:
    """Desensitized provider failure: real cause preserved, secrets stripped."""

    return NormalizedRejection(
        provider_code=provider_code,
        normalized_code=normalized_code,
        safe_message=redact_secrets(message)[:500],
        retryable=normalized_code in _RETRYABLE_CODES,
    )


__all__ = [
    "AdmissionVerdict3",
    "NormalizedRejection",
    "PlanError",
    "RepairAction",
    "RepairKind",
    "TargetFact",
    "TargetPlan",
    "TargetStatus",
    "admit_batch",
    "admit_single",
    "derive_repair_for_reason",
    "derive_target_status",
    "normalize_rejection",
    "project_plan",
    "validate_repair_action",
]
