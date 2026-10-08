"""P0.2 — execution result and failure records.

Why the failure type has a different name than the spec's
---------------------------------------------------------
`hevi/execution/models.py` already defines ``ExecutionFailure`` as a ``StrEnum``: the
*vocabulary* of why an attempt failed (SOURCE_MISSING, EXECUTOR_FAILED,
VALIDATION_FAILED, …). The spec's ``ExecutionFailure`` is a different shape -- a
*record* carrying an operation id, a retry decision and a transaction id.

Defining a second class with that name in the same codebase would repeat the exact
collision that module's own docstring warns about, where two types named
``ExecutionReceipt`` end up with two meanings. So the enum keeps the name and the
record is ``ExecutionFailureRecord``. The enum is referenced, not duplicated, so the
failure vocabulary has one source.

Why ``retryable`` is derived and not asserted
---------------------------------------------
§10 splits failures into three levels: transient, provider, semantic. Only the first
may retry automatically, and a semantic failure must raise a RepairIncident instead.

A hand-supplied ``retryable=True`` would let a caller retry an invalid TimelineIR
forever. So the level is computed from the error type and stored alongside the caller's
intent; disagreement is preserved rather than silently resolved, because a caller who
believes a failure is transient when it is not is exactly the bug this catches.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from hevi.execution.models import ExecutionFailure
from hevi.production.operation import ProductionOperation


class ExecutionFailureLevel(StrEnum):
    """§10's three retry levels."""

    TRANSIENT = "TRANSIENT"
    PROVIDER = "PROVIDER"
    SEMANTIC = "SEMANTIC"


#: Error types that may be retried automatically.
#:
#: Deliberately a set of *error kinds*, not of provider ids: a 429 is transient for
#: every provider, and encoding a provider-specific list here would make this table a
#: second place provider behaviour is declared.
_TRANSIENT_ERRORS = frozenset(
    {
        "timeout",
        "rate_limited",
        "connection_reset",
        "temporary_filesystem_failure",
        "browser_launch_failure",
        "ffmpeg_transient",
        "lock_contention",
    }
)

#: Error types where the operation is well-formed but the provider could not serve it.
#: Retry may switch provider -- but only through the canonical policy.
_PROVIDER_ERRORS = frozenset(
    {
        "provider_unavailable",
        "capability_mismatch",
        "invalid_provider_response",
        "quota_exhausted",
    }
)


def classify_failure(error_type: str) -> ExecutionFailureLevel:
    """Map an error type onto a retry level.

    Unknown types are ``SEMANTIC``. Defaulting unknown to retryable is how a
    malformed plan turns into an infinite retry loop; defaulting to semantic means an
    unrecognised transient error costs one manual retry, which is recoverable.
    """
    normalized = error_type.strip().lower()
    if normalized in _TRANSIENT_ERRORS:
        return ExecutionFailureLevel.TRANSIENT
    if normalized in _PROVIDER_ERRORS:
        return ExecutionFailureLevel.PROVIDER
    return ExecutionFailureLevel.SEMANTIC


class ExecutionResult(BaseModel):
    """The outcome of one operation attempt.

    ``FAILED`` and ``SKIPPED`` are distinct: a skipped operation did not fail, and
    collapsing the two would make a dependency-driven skip look like an error in the
    final validation.
    """

    model_config = ConfigDict(frozen=True)

    operation_id: str
    status: str = "SUCCEEDED"

    artifacts: tuple[str, ...] = ()
    receipt_refs: tuple[str, ...] = ()
    duration_ms: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.status == "SUCCEEDED"

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class ExecutionFailureRecord(BaseModel):
    """A failure that happened, recorded whether or not anything was done about it.

    §35 forbids silent failure. This type exists so a failure cannot be swallowed: it
    must be constructible, and the transaction records it either way.
    """

    model_config = ConfigDict(frozen=True)

    failure_id: str
    production_id: str
    operation_id: str | None = None
    stage: str = "execute"

    #: Free-form error kind (``"timeout"``, ``"invalid_timeline"``, …). Classified by
    #: :func:`classify_failure` rather than by the caller.
    error_type: str = "unknown"
    message: str = ""

    #: What the caller *believed*. Kept even when it disagrees with ``level``, because a
    #: caller asserting a semantic failure is retryable is a bug worth surfacing.
    caller_claimed_retryable: bool | None = None
    #: The computed decision. Callers read this, not the claim.
    level: ExecutionFailureLevel = ExecutionFailureLevel.SEMANTIC

    provider_ref: str | None = None
    artifact_refs: tuple[str, ...] = ()
    transaction_id: str = ""
    traceback_ref: str | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def for_operation(
        cls,
        *,
        production_id: str,
        operation: ProductionOperation,
        transaction_id: str,
        stage: str,
        error_type: str,
        message: str,
        provider_ref: str | None = None,
        artifact_refs: tuple[str, ...] = (),
        traceback_ref: str | None = None,
        caller_claimed_retryable: bool | None = None,
    ) -> ExecutionFailureRecord:
        level = classify_failure(error_type)
        digest = hashlib.sha256(
            "|".join(
                [production_id, operation.operation_id, stage, error_type, transaction_id]
            ).encode("utf-8")
        ).hexdigest()[:16]
        return cls(
            failure_id=f"failure-{digest}",
            production_id=production_id,
            operation_id=operation.operation_id,
            stage=stage,
            error_type=error_type,
            message=message,
            provider_ref=provider_ref or operation.provider_ref,
            artifact_refs=artifact_refs,
            transaction_id=transaction_id,
            traceback_ref=traceback_ref,
            caller_claimed_retryable=caller_claimed_retryable,
            level=level,
        )

    @property
    def retryable(self) -> bool:
        """Only level 1 may retry without a decision by the repair policy.

        A ``PROVIDER`` failure may be retried against a different provider, but that
        routing decision belongs to ``RepairPolicy``; this property stays False so no
        naive retry loop re-executes the same call.
        """
        return self.level is ExecutionFailureLevel.TRANSIENT

    @property
    def requires_repair_incident(self) -> bool:
        """§10 level 3: a semantic failure must become a RepairIncident.

        The record does not create one -- ``RepairPolicy`` owns that -- but this
        property is what a caller checks so the omission cannot be an oversight.
        """
        return self.level is ExecutionFailureLevel.SEMANTIC

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class AdapterError(RuntimeError):
    """An adapter declaring *why* it failed, in the vocabulary above.

    Without this, `failure_from_exception` has to infer the error kind from the
    exception class name, so a `RuntimeError("simulated timeout")` classifies as
    SEMANTIC and a genuinely transient failure is never retried. Inferring from the
    message string would be worse: it makes retry policy depend on prose.

    An adapter raises this with an explicit ``error_type``; the executor never guesses.
    """

    def __init__(self, error_type: str, message: str = "") -> None:
        super().__init__(message or error_type)
        self.error_type = error_type
        self.message = message or error_type


def failure_from_exception(
    *,
    production_id: str,
    operation: ProductionOperation,
    transaction_id: str,
    stage: str,
    exc: BaseException,
) -> ExecutionFailureRecord:
    """Build a record from an exception.

    An `AdapterError` carries its own vocabulary term and is trusted. Anything else
    falls back to the exception class name, matched against the existing
    ``ExecutionFailure`` members first so the established vocabulary is preferred over
    inventing a parallel spelling of the same condition.
    """
    if isinstance(exc, AdapterError):
        return ExecutionFailureRecord.for_operation(
            production_id=production_id,
            operation=operation,
            transaction_id=transaction_id,
            stage=stage,
            error_type=exc.error_type,
            message=exc.message,
        )

    known = {member.value for member in ExecutionFailure}
    error_type = type(exc).__name__.lower()
    for member in ExecutionFailure:
        if member.value in error_type or error_type in member.value:
            error_type = member.value
            break
    else:
        if error_type not in known and error_type.endswith("error"):
            error_type = error_type[: -len("error")]
    return ExecutionFailureRecord.for_operation(
        production_id=production_id,
        operation=operation,
        transaction_id=transaction_id,
        stage=stage,
        error_type=error_type,
        message=str(exc) or type(exc).__name__,
    )


@dataclass(frozen=True)
class AttemptRecord:
    """One attempt at one operation, successful or not.

    Kept as a dataclass rather than a model because it is bookkeeping, not a wire
    contract, and it accumulates in bulk on the transaction.
    """

    operation_id: str
    attempt: int
    result: ExecutionResult | None = None
    failure: ExecutionFailureRecord | None = None
    idempotency_key: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.result is not None and self.result.succeeded


__all__ = [
    "AdapterError",
    "AttemptRecord",
    "ExecutionFailureLevel",
    "ExecutionFailureRecord",
    "ExecutionResult",
    "classify_failure",
    "failure_from_exception",
]
