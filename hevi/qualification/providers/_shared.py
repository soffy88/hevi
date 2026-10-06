"""Shared adapter helpers. No measurement happens here — only execution bookkeeping."""

from __future__ import annotations

from pathlib import Path

from hevi.qualification.models import (
    AdapterAvailability,
    AdapterFailure,
    Availability,
    ExecutionResult,
    ExecutionState,
    QualificationRequest,
    RuntimeUnavailable,
    new_execution_id,
)


def check_locator(request: QualificationRequest, provider_id: str) -> str:
    """Confirm a locator names a non-empty file, or raise the right failure.

    Split deliberately:

    * ``RuntimeUnavailable`` — we never started. The framework reports
      ``BLOCKED_BY_RUNTIME``.
    * ``AdapterFailure(NO_ARTIFACT)`` — we ran, exit was zero, and there is no file.
      Conflating the two is how a working renderer gets reported as broken.
    """
    target = Path(request.output_path)
    if not target.exists():
        raise AdapterFailure(
            ExecutionState.NO_ARTIFACT,
            f"exit reported success but {target} does not exist",
        )
    if not target.read_bytes():
        raise AdapterFailure(
            ExecutionState.NO_ARTIFACT, f"{target} exists but is empty"
        )
    return str(target)


def result_for(
    request: QualificationRequest, metadata: dict[str, str] | None = None
) -> ExecutionResult:
    """Build an ExecutionResult: locator, id, metadata. Nothing measured."""
    return ExecutionResult(
        artifact_locator=str(request.output_path),
        execution_id=new_execution_id(request.provider_id),
        runtime_metadata={k: str(v) for k, v in (metadata or {}).items()},
    )


def unavailable(reason: str) -> AdapterAvailability:
    return AdapterAvailability(Availability.MISSING_RUNTIME, reason)


__all__ = [
    "AdapterFailure",
    "ExecutionResult",
    "ExecutionState",
    "RuntimeUnavailable",
    "check_locator",
    "result_for",
    "unavailable",
]
