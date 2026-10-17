"""Shot readiness state machine and machine-readable preflight gate."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import BaseModel, Field

from hevi.production_graph.domain import (
    CanonicalShot,
    ReadinessState,
    ReferenceRole,
    ShotReadinessResult,
)


class ReadinessTransitionError(ValueError):
    """Raised when a shot attempts an illegal lifecycle transition."""


_TRANSITIONS: Mapping[ReadinessState, frozenset[ReadinessState]] = {
    ReadinessState.DRAFT: frozenset({ReadinessState.ANALYZED}),
    ReadinessState.ANALYZED: frozenset(
        {
            ReadinessState.ASSETS_PENDING,
            ReadinessState.REFERENCES_PENDING,
            ReadinessState.PREFLIGHT_FAILED,
            ReadinessState.READY,
        }
    ),
    ReadinessState.ASSETS_PENDING: frozenset(
        {ReadinessState.REFERENCES_PENDING, ReadinessState.PREFLIGHT_FAILED, ReadinessState.READY}
    ),
    ReadinessState.REFERENCES_PENDING: frozenset(
        {ReadinessState.PREFLIGHT_FAILED, ReadinessState.READY}
    ),
    ReadinessState.PREFLIGHT_FAILED: frozenset(
        {
            ReadinessState.ANALYZED,
            ReadinessState.ASSETS_PENDING,
            ReadinessState.REFERENCES_PENDING,
            ReadinessState.READY,
        }
    ),
    ReadinessState.READY: frozenset({ReadinessState.QUEUED}),
    ReadinessState.QUEUED: frozenset({ReadinessState.GENERATING}),
    ReadinessState.GENERATING: frozenset({ReadinessState.GENERATED, ReadinessState.QA_FAILED}),
    ReadinessState.GENERATED: frozenset({ReadinessState.QA_FAILED, ReadinessState.QA_PASSED}),
    ReadinessState.QA_FAILED: frozenset({ReadinessState.QUEUED, ReadinessState.ANALYZED}),
    ReadinessState.QA_PASSED: frozenset({ReadinessState.APPROVED}),
    ReadinessState.APPROVED: frozenset({ReadinessState.LOCKED}),
    ReadinessState.LOCKED: frozenset(),
}


def transition_shot(shot: CanonicalShot, target: ReadinessState) -> CanonicalShot:
    current = ReadinessState(shot.readiness_state)
    if current == target:
        return shot
    if target not in _TRANSITIONS[current]:
        raise ReadinessTransitionError(f"illegal shot readiness transition: {current} -> {target}")
    return shot.model_copy(update={"readiness_state": target})


def assert_dispatchable(shot: CanonicalShot) -> None:
    if ReadinessState(shot.readiness_state) is not ReadinessState.READY:
        raise ReadinessTransitionError(
            f"generation dispatch requires READY shot; got {shot.readiness_state}"
        )


class ReadinessContext(BaseModel):
    narrative_valid: bool = True
    assets_ready: bool = True
    references_ready: bool = True
    continuity_valid: bool = True
    provider_supported: bool = True
    budget_available: bool = True
    resources_available: bool = True
    required_reference_roles: set[ReferenceRole] = Field(default_factory=set)
    available_reference_roles: set[ReferenceRole] = Field(default_factory=set)
    warnings: list[dict[str, str]] = Field(default_factory=list)
    details: dict[str, object] = Field(default_factory=dict)


@dataclass(frozen=True)
class _Check:
    name: str
    passed: bool
    code: str
    detail: str


def _checks(context: ReadinessContext) -> list[_Check]:
    refs_ok = (
        context.references_ready
        and context.required_reference_roles <= context.available_reference_roles
    )
    return [
        _Check(
            "narrative",
            context.narrative_valid,
            "NARRATIVE_INVALID",
            "narrative links are incomplete",
        ),
        _Check("assets", context.assets_ready, "ASSETS_PENDING", "required assets are not ready"),
        _Check(
            "references", refs_ok, "REFERENCES_PENDING", "required typed references are missing"
        ),
        _Check(
            "continuity",
            context.continuity_valid,
            "CONTINUITY_INVALID",
            "continuity constraints fail",
        ),
        _Check(
            "provider_capability",
            context.provider_supported,
            "CAPABILITY_UNSUPPORTED",
            "provider cannot satisfy the shot",
        ),
        _Check(
            "budget", context.budget_available, "BUDGET_EXCEEDED", "budget gate rejected the shot"
        ),
        _Check(
            "resource",
            context.resources_available,
            "RESOURCE_UNAVAILABLE",
            "runtime resources are unavailable",
        ),
    ]


def evaluate_readiness(shot: CanonicalShot, context: ReadinessContext) -> ShotReadinessResult:
    checks = _checks(context)
    blockers = [
        {"code": check.code, "gate": check.name, "detail": check.detail}
        for check in checks
        if not check.passed
    ]
    if blockers:
        state = ReadinessState.PREFLIGHT_FAILED
        if not context.assets_ready:
            state = ReadinessState.ASSETS_PENDING
        elif not context.references_ready or (
            context.required_reference_roles - context.available_reference_roles
        ):
            state = ReadinessState.REFERENCES_PENDING
    else:
        state = ReadinessState.READY
    return ShotReadinessResult(
        shot_id=shot.id,
        revision_id=str(shot.revision_id or ""),
        state=state,
        passed=not blockers,
        blockers=blockers,
        warnings=list(context.warnings),
        checks={check.name: check.passed for check in checks},
    )


def prepare_shot(
    shot: CanonicalShot, context: ReadinessContext
) -> tuple[CanonicalShot, ShotReadinessResult]:
    """Advance a draft through analysis and preflight without skipping gates."""

    analyzed = shot
    if ReadinessState(analyzed.readiness_state) is ReadinessState.DRAFT:
        analyzed = transition_shot(analyzed, ReadinessState.ANALYZED)
    result = evaluate_readiness(analyzed, context)
    prepared = transition_shot(analyzed, result.state)
    return prepared, result


__all__ = [
    "ReadinessContext",
    "ReadinessTransitionError",
    "assert_dispatchable",
    "evaluate_readiness",
    "prepare_shot",
    "transition_shot",
]
