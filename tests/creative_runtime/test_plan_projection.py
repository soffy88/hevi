"""W7 gates: single-source projection, pre-submit admission, actionable blocks."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hevi.creative.layer4.currency import ArtifactCurrency
from hevi.creative.layer4.endpoint_lifecycle import (
    CapabilityRequirement,
    DeclarativeEndpointDefinition,
)
from hevi.creative.layer4.plan_projection import (
    PlanError,
    RepairAction,
    RepairKind,
    TargetFact,
    TargetStatus,
    admit_batch,
    admit_single,
    derive_repair_for_reason,
    derive_target_status,
    normalize_rejection,
    project_plan,
    validate_repair_action,
)
from tests.creative_runtime.test_endpoint_lifecycle import _definition as _endpoint


def _fact(target_id: str = "clip-1", **kw) -> TargetFact:
    args: dict = {"currency": ArtifactCurrency.CURRENT, **kw}
    return TargetFact(target_id=target_id, **args)


def test_projection_single_source() -> None:
    """PLAN_PROJECTION_SINGLE_SOURCE: pure function of inputs, twice equal."""

    facts = (
        _fact("a", verified_complete=True),
        _fact("b", currency=ArtifactCurrency.STALE),
        _fact("c", currency=ArtifactCurrency.MISSING),
    )
    first, second = project_plan(facts), project_plan(facts)
    assert first == second
    assert [p.status for p in first] == [
        TargetStatus.COMPLETED,
        TargetStatus.STALE,
        TargetStatus.MISSING,
    ]
    assert first[0].next_actions == ()
    assert first[1].next_actions == ("reuse-or-regenerate:b",)
    assert first[2].next_actions == ("generate:c",)


def test_status_derivation_matrix() -> None:
    assert derive_target_status(_fact(currency=None)) is TargetStatus.MISSING
    assert derive_target_status(_fact(currency=None, required=False)) is TargetStatus.READY
    assert derive_target_status(_fact(currency=ArtifactCurrency.BLOCKED)) is TargetStatus.BLOCKED
    assert (
        derive_target_status(_fact(blocking_reason="missing reference: Ghost"))
        is TargetStatus.BLOCKED
    )
    assert derive_target_status(_fact(basis_readable=False)) is TargetStatus.BLOCKED
    assert derive_target_status(_fact()) is TargetStatus.READY


def test_blocked_reason_actionable() -> None:
    """BLOCKED_REASON_ACTIONABLE: blocks always carry reason + valid repair."""

    plans = project_plan(
        (
            _fact("x", basis_readable=False),
            _fact(
                "y",
                blocking_reason="missing reference: Ghost",
                repair_actions=(
                    RepairAction(action_id="r-y", kind=RepairKind.FIX_REFERENCES, target_id="y"),
                ),
            ),
        )
    )
    assert plans[0].status is TargetStatus.BLOCKED
    assert plans[0].blocking_reason
    assert plans[0].repair_actions[0].kind is RepairKind.RESTORE_ASSET
    assert plans[1].repair_actions[0].kind is RepairKind.FIX_REFERENCES
    assert plans[0].next_actions[0].startswith("repair:")
    from hevi.creative.layer4.plan_projection import TargetPlan

    with pytest.raises(ValidationError, match="PLAN_BLOCKED_NEEDS_REASON"):
        TargetPlan(target_id="z", status=TargetStatus.BLOCKED)
    with pytest.raises(ValidationError, match="PLAN_BLOCKED_NEEDS_REPAIR_ACTION"):
        TargetPlan(target_id="z", status=TargetStatus.BLOCKED, blocking_reason="r")


def test_repair_action_valid() -> None:
    """REPAIR_ACTION_VALID: repairs must name real targets."""

    action = RepairAction(action_id="r1", kind=RepairKind.RETRY_TARGET, target_id="a")
    assert validate_repair_action(action, ("a", "b")) is action
    with pytest.raises(PlanError, match="PLAN_REPAIR_UNKNOWN_TARGET"):
        validate_repair_action(action, ("b",))
    derived = derive_repair_for_reason("provider failure: timeout", "clip-9")
    assert derived.kind is RepairKind.RETRY_TARGET
    assert derived.target_id == "clip-9"


def _requirement(**kw) -> CapabilityRequirement:
    args: dict = {"media_type": "video", "duration_s": 5, **kw}
    return CapabilityRequirement(**args)


def _provider() -> DeclarativeEndpointDefinition:
    return _endpoint()


def test_pre_submit_capability_admission() -> None:
    """PRE_SUBMIT_CAPABILITY_ADMISSION: unsupported combos refuse before submit."""

    blocked = admit_single(_provider(), _requirement(duration_s=30))
    assert blocked.decision == "blocked"
    assert blocked.admitted_items == ()
    assert any("duration 30s" in reason for reason in blocked.reasons)
    admitted = admit_single(_provider(), _requirement())
    assert admitted.decision == "admit"
    assert admitted.admitted_items == ("item",)
    confirm = admit_single(_provider(), _requirement(), estimated_cost=9.0, confirm_above_cost=5.0)
    assert confirm.decision == "confirm"


def test_batch_admission_all_or_none() -> None:
    provider = _provider()
    items = (
        ("a", provider, _requirement(), 1.0),
        ("b", provider, _requirement(duration_s=30), 1.0),
        ("c", provider, _requirement(), 1.0),
    )
    verdict = admit_batch(items)
    assert verdict.decision == "blocked"
    assert verdict.admitted_items == ()  # zero items admitted, zero tasks created
    assert any(reason.startswith("b:") for reason in verdict.reasons)
    ok = admit_batch((("a", provider, _requirement(), 1.0), ("c", provider, _requirement(), 2.0)))
    assert ok.decision == "admit"
    assert ok.admitted_items == ("a", "c")
    confirm = admit_batch((("a", provider, _requirement(), 9.0),), confirm_above_cost=5.0)
    assert confirm.decision == "confirm"


def test_rejection_normalization_desensitized_and_retryable() -> None:
    retryable = normalize_rejection(
        provider_code="429", message="busy, api_key: SECRET999", normalized_code="RATE_LIMITED"
    )
    assert retryable.retryable is True
    assert "SECRET999" not in retryable.safe_message
    fatal = normalize_rejection(
        provider_code="400", message="bad prompt", normalized_code="INVALID_REQUEST"
    )
    assert fatal.retryable is False
    assert fatal.provider_code == "400"
