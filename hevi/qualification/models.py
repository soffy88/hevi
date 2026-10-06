"""HEVI P9.1.d.1 — the qualification adapter contract.

An adapter **executes** a provider. It does not **judge** it.

    ProviderQualification.available()  ->  can this run at all?
    ProviderQualification.execute(req)  ->  ExecutionResult

:class:`ExecutionResult` carries a locator and runtime metadata. It deliberately has no
`checksum`, `duration_s`, `codec` or `passed` — an adapter that measured any of those
would be a second artifact authority, which is the defect this whole phase removes.

The verdict belongs to the framework, which reads bytes, computes the digest, issues a
receipt and runs P8.4 validation. An adapter returns ``QUALIFIED`` nowhere; there is no
field in which to return it.

Two failure modes are distinguished and never flattened:

* :class:`RuntimeUnavailable` — nothing was started. The environment lacks the tool.
  Reported as ``BLOCKED_BY_RUNTIME``, not as a failure.
* :class:`AdapterFailure` — something ran and did not work. The reason is retained.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class Availability(StrEnum):
    """Whether an adapter could run, before anything is attempted."""

    AVAILABLE = "available"
    MISSING_RUNTIME = "missing_runtime"
    NOT_CONFIGURED = "not_configured"


class ExecutionState(StrEnum):
    """What happened when the adapter executed.

    ``NO_ARTIFACT`` is separate from ``FAILED`` because an exit code of zero that
    produced no file is a materially different fact from a crash, and P9.1.a
    established that the *reason* is what distinguishes them.
    """

    OK = "ok"
    NO_ARTIFACT = "no_artifact"
    FAILED = "failed"
    NOT_ATTEMPTED = "not_attempted"
    BLOCKED_RUNTIME = "blocked_runtime"


class RuntimeUnavailable(Exception):
    """The provider's runtime is absent. Nothing was attempted."""


class AdapterFailure(Exception):
    """The provider ran and did not produce a usable artifact."""

    def __init__(
        self,
        state: ExecutionState,
        reason: str,
        *,
        error_type: str = "",
        http_status: int | None = None,
    ) -> None:
        super().__init__(f"{state.value}:{reason}")
        self.state = state
        self.reason = reason
        #: a coarse failure class, so a caller can map a failure without parsing prose.
        #: P9.2 uses it to tell "the provider is down" from "it refused us" from
        #: "it never finished" — three situations that need three different verdicts.
        self.error_type = error_type
        self.http_status = http_status


@dataclass(frozen=True)
class QualificationRequest:
    """What to render. Identifies the source; says nothing about the result."""

    provider_id: str
    output_path: str
    #: provider-specific inputs (composition id, scene, ffmpeg argv, …)
    params: dict[str, Any] = field(default_factory=dict)
    #: for encoders: an existing artifact to transform
    input_path: str = ""
    media_type: str = "VIDEO"
    timeout_s: float = 900.0


@dataclass(frozen=True)
class ExecutionResult:
    """A locator plus what the runtime reported. Never a verdict, never a measurement.

    The absence of ``checksum``/``duration_s``/``codec``/``passed`` is the contract.
    Adding any of them makes the adapter a second artifact authority, and
    ``test_execution_result_carries_no_measurement`` fails.
    """

    artifact_locator: str
    execution_id: str
    runtime_metadata: dict[str, str] = field(default_factory=dict)

    def exists(self) -> bool:
        return bool(self.artifact_locator) and Path(self.artifact_locator).is_file()

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_locator": self.artifact_locator,
            "execution_id": self.execution_id,
            "runtime_metadata": dict(self.runtime_metadata),
        }


@dataclass(frozen=True)
class AdapterAvailability:
    """Result of an availability probe — deliberately not a verdict."""

    state: Availability
    reason: str = ""

    @property
    def can_run(self) -> bool:
        return self.state is Availability.AVAILABLE

    def __bool__(self) -> bool:
        return self.can_run

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state.value, "reason": self.reason}


@runtime_checkable
class ProviderQualification(Protocol):
    """Executes one provider. Judges nothing."""

    provider_id: str

    def available(self) -> AdapterAvailability: ...

    def execute(self, request: QualificationRequest) -> ExecutionResult: ...


def new_execution_id(provider_id: str) -> str:
    return f"exec-{provider_id}-{datetime.now(UTC).timestamp():.0f}"


__all__ = [
    "AdapterAvailability",
    "AdapterFailure",
    "Availability",
    "ExecutionResult",
    "ExecutionState",
    "ProviderQualification",
    "QualificationRequest",
    "RuntimeUnavailable",
    "new_execution_id",
]
