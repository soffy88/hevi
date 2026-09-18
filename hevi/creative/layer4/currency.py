"""Explicit artifact currency semantics (Gap Closure W2, ARC-J02/H09).

Every formal artifact is judged against current production inputs as one
of exactly four states:

- CURRENT: provenance matches current dependency revisions; default presentation.
- STALE: intact, viewable, exportable, composable — but a dependency moved.
  Never auto-deleted, never auto re-billed.
- MISSING: production state needs the artifact, but no valid one exists.
- BLOCKED: the artifact cannot be lawfully produced; carries blocking_reason
  plus a repair_action. Blocked is never treated as missing, so no paid
  rework is ever launched against it.

There is no fifth fuzzy state. Reasons travel in dedicated fields, never
smuggled into the currency value.

Role split (one module, three documented roles, no meaningless assets):

- OBASE role: :class:`ArtifactCurrency`, :class:`CurrencyEvaluation` —
  canonical manifest/artifact semantics.
- OSKILL role: :func:`evaluate_currency`, :func:`evaluate_all`,
  :func:`revision_matches`, :func:`invalidate_dependents`,
  :func:`assert_no_usable_loss` — stateless pure evaluators. Project-id
  logic never enters them; callers project Production Graph edges in.
- HEVI_LAYER4 role: callers resolve project dependencies into the
  ``dependency_revisions`` / ``edges`` inputs and render evaluations.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ArtifactCurrency(StrEnum):
    """The only four currency states. No UNKNOWN_CURRENT, no PARTIAL_OK."""

    CURRENT = "current"
    STALE = "stale"
    MISSING = "missing"
    BLOCKED = "blocked"


class CurrencyError(ValueError):
    """Refusal with a stable machine code."""


class ArtifactBasis(BaseModel):
    """What the evaluator needs to know about one artifact. Pure input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    exists: bool = True
    integrity_ok: bool = True
    needed: bool = True
    dependency_revision: str = ""
    basis_readable: bool = True
    basis_read_failure: str | None = None
    blocking_reason: str | None = None
    repair_action: str | None = None


class CurrencyEvaluation(BaseModel):
    """One judged artifact. Reason fields are separate from currency."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str
    role: str
    currency: ArtifactCurrency
    reason: str = Field(min_length=1)
    blocking_reason: str | None = None
    repair_action: str | None = None
    basis_revision: str = ""
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _blocked_carries_reason_and_repair(self) -> CurrencyEvaluation:
        if self.currency is ArtifactCurrency.BLOCKED and (
            not self.blocking_reason or not self.repair_action
        ):
            raise CurrencyError("CURRENCY_BLOCKED_NEEDS_REASON_AND_REPAIR")
        if self.currency is not ArtifactCurrency.BLOCKED and self.blocking_reason:
            raise CurrencyError("CURRENCY_ONLY_BLOCKED_CARRIES_BLOCKING_REASON")
        return self

    @property
    def usable(self) -> bool:
        """STALE stays usable: viewable, exportable, composable."""

        return self.currency in (ArtifactCurrency.CURRENT, ArtifactCurrency.STALE)


def revision_matches(basis_revision: str, dependency_revisions: Mapping[str, str]) -> bool:
    """Every gated key must agree; undeclared keys cannot flip currency.

    The basis revision is a "+"-joined token set (``graph@7+prompt@1``) or a
    legacy bare revision. Token-exact comparison avoids substring false
    positives (``graph@7`` must not match ``graph@71``).
    """

    if not dependency_revisions:
        return True
    if not basis_revision:
        return False
    tokens = set(basis_revision.split("+"))
    for key, revision in dependency_revisions.items():
        if basis_revision != revision and f"{key}@{revision}" not in tokens:
            return False
    return True


def evaluate_currency(
    basis: ArtifactBasis,
    dependency_revisions: Mapping[str, str] | None = None,
) -> CurrencyEvaluation:
    """Judge one artifact. Stateless; never deletes, never re-bills, never guesses."""

    deps = dict(dependency_revisions or {})
    if not basis.basis_readable:
        return CurrencyEvaluation(
            artifact_id=basis.artifact_id,
            role=basis.role,
            currency=ArtifactCurrency.BLOCKED,
            reason=basis.basis_read_failure or "artifact basis unreadable",
            blocking_reason=basis.blocking_reason or "unreadable artifact basis",
            repair_action=basis.repair_action
            or "repair artifact basis, then regenerate explicitly",
            basis_revision=basis.dependency_revision,
        )
    if not basis.exists or not basis.integrity_ok:
        if not basis.needed:
            return CurrencyEvaluation(
                artifact_id=basis.artifact_id,
                role=basis.role,
                currency=ArtifactCurrency.STALE,
                reason="artifact file absent but role not currently needed; prior record retained",
                basis_revision=basis.dependency_revision,
            )
        return CurrencyEvaluation(
            artifact_id=basis.artifact_id,
            role=basis.role,
            currency=ArtifactCurrency.MISSING,
            reason="production state needs this artifact and no valid file exists",
            basis_revision=basis.dependency_revision,
        )
    if revision_matches(basis.dependency_revision, deps):
        return CurrencyEvaluation(
            artifact_id=basis.artifact_id,
            role=basis.role,
            currency=ArtifactCurrency.CURRENT,
            reason="provenance matches current dependency revisions",
            basis_revision=basis.dependency_revision,
        )
    return CurrencyEvaluation(
        artifact_id=basis.artifact_id,
        role=basis.role,
        currency=ArtifactCurrency.STALE,
        reason="artifact intact but a dependency revision moved; explicit reuse or regenerate required",
        basis_revision=basis.dependency_revision,
    )


def evaluate_all(
    bases: tuple[ArtifactBasis, ...],
    dependency_revisions: Mapping[str, str] | None = None,
) -> tuple[CurrencyEvaluation, ...]:
    """Judge a batch; every entry judged, none dropped."""

    return tuple(evaluate_currency(basis, dependency_revisions) for basis in bases)


def invalidate_dependents(
    changed_dependency_keys: tuple[str, ...],
    edges: tuple[tuple[str, str], ...],
) -> tuple[str, ...]:
    """Scoped invalidation over caller-projected Production Graph edges.

    ``edges`` maps ``(dependent_artifact_id, dependency_key)``. Only
    dependents of actually-changed keys are returned, preserving input
    order, deduplicated — a character appearance change invalidates its
    storyboards/videos/presentations, never the whole project.
    """

    changed = set(changed_dependency_keys)
    affected: list[str] = []
    for dependent_id, dependency_key in edges:
        if dependency_key in changed and dependent_id not in affected:
            affected.append(dependent_id)
    return tuple(affected)


def assert_no_usable_loss(
    previous: tuple[CurrencyEvaluation, ...],
    current: tuple[CurrencyEvaluation, ...],
    required_roles: tuple[str, ...],
) -> None:
    """Paid-artifact preservation guard: regeneration must not orphan a role.

    For every required role usable before, at least one evaluation for that
    role must remain usable after. Raises LOST_VALID_ARTIFACT otherwise —
    callers must retain the old artifact instead of overwriting it.
    """

    before: dict[str, bool] = {}
    for evaluation in previous:
        if evaluation.role in required_roles and evaluation.usable:
            before[evaluation.role] = True
    for role in before:
        if not any(evaluation.role == role and evaluation.usable for evaluation in current):
            raise CurrencyError(f"CURRENCY_LOST_VALID_ARTIFACT:{role}")


def annotate_selections(
    evaluations: tuple[CurrencyEvaluation, ...],
) -> dict[str, dict[str, str | None]]:
    """Parallel annotation map for readers; never mutates stored manifests."""

    return {
        evaluation.artifact_id: {
            "currency": evaluation.currency.value,
            "reason": evaluation.reason,
            "blocking_reason": evaluation.blocking_reason,
            "repair_action": evaluation.repair_action,
        }
        for evaluation in evaluations
    }


__all__ = [
    "ArtifactBasis",
    "ArtifactCurrency",
    "CurrencyError",
    "CurrencyEvaluation",
    "annotate_selections",
    "assert_no_usable_loss",
    "evaluate_all",
    "evaluate_currency",
    "invalidate_dependents",
    "revision_matches",
]
