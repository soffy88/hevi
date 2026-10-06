"""HEVI P8.3 — Execution runs and production receipts.

Naming, because it is the whole problem
--------------------------------------
P6 already defines a type called ``ExecutionReceipt``
(``hevi/production/p6/production_runtime.py``) meaning *proof that a delegate ran*:

    runtime_id, entrypoint_ref, produced

This module needs proof of a different thing entirely — *that an artifact was
produced and validated*:

    receipt_id, run_id, artifact_id, artifact_checksum, producer, validation_result

Defining a second ``ExecutionReceipt`` would put two types with one name and two
meanings in the same codebase, which is precisely the defect P8.2 found in its own
``AcquisitionState.FAILED`` colliding with ``RunState.failed``. It would also breach
``NO_SECOND_PRODUCTION_AUTHORITY``.

So this is :class:`ProductionReceipt`, and the two are not interchangeable:

    P6 ExecutionReceipt   a delegate ran          orchestration
    P8.3 ProductionReceipt an artifact is proven   execution

Neither is derived from the other, and neither constructs the other. A P6 receipt with
``produced=True`` is not a production receipt; a production receipt does not assert
that any delegate ran.

``artifact_exists() != production_success``
------------------------------------------
A file on disk proves bytes were written. It does not prove they are playable, that
they came from the source we meant, or that a render completed rather than crashed
after writing a partial file. So a receipt cannot be minted from a path. It is issued
by :func:`hevi.execution.execute.issue_receipt`, which takes the artifact **bytes**,
requires a digest over them, and requires a :class:`ValidationResult` that observed
those same bytes.

``COMPLETED`` is not ``PRODUCED``
---------------------------------
:class:`ExecutionState` is namespaced (``execution_completed``) so it cannot collide
with ``RunState`` on the wire. It marks an attempt that finished, which is not a
verdict: only P6 may set ``RunState.PRODUCED``, at its single construction site,
having been handed a receipt. This package never names ``RunState``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from hevi.validation.artifact import ValidationResult

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


class ExecutionState(StrEnum):
    """How far an execution attempt got.

    Values are namespaced because ``RunState`` already occupies ``completed``-shaped
    and ``failed``-shaped territory. A bare ``failed`` would be indistinguishable from
    ``RunState.failed`` after serialisation.
    """

    REQUESTED = "execution_requested"
    RUNNING = "execution_running"
    COMPLETED = "execution_completed"
    FAILED = "execution_failed"


class ExecutionFailure(StrEnum):
    """Why an execution attempt did not produce a receipt.

    Distinct from acquisition failures: nothing here says a download broke, and a
    receipt that cannot be issued is a different problem from a source that was never
    acquired.
    """

    SOURCE_MISSING = "source_missing"
    EXECUTOR_FAILED = "executor_failed"
    ARTIFACT_MISSING = "artifact_missing"
    ARTIFACT_UNREADABLE = "artifact_unreadable"
    VALIDATION_FAILED = "validation_failed"
    VALIDATION_NOT_RUN = "validation_not_run"
    PAYLOAD_MISMATCH = "payload_mismatch"
    ALREADY_RECEIPTED = "already_receipted"


@dataclass(frozen=True)
class ExecutionRun:
    """One execution attempt. A record of intent and progress, not a verdict."""

    run_id: str
    source_id: str
    executor: str
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    state: ExecutionState = ExecutionState.REQUESTED

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("EXECUTION_RUN_WITHOUT_ID:run_id required")
        if not self.source_id:
            raise ValueError(f"EXECUTION_RUN_WITHOUT_SOURCE:{self.run_id}")
        if not self.executor:
            raise ValueError(f"EXECUTION_RUN_WITHOUT_EXECUTOR:{self.run_id}")
        if not isinstance(self.state, ExecutionState):
            raise ValueError(f"UNKNOWN_EXECUTION_STATE:{self.state!r}")

    def completed(self) -> ExecutionRun:
        return ExecutionRun(
            run_id=self.run_id, source_id=self.source_id, executor=self.executor,
            started_at=self.started_at, state=ExecutionState.COMPLETED,
        )

    def failed(self) -> ExecutionRun:
        return ExecutionRun(
            run_id=self.run_id, source_id=self.source_id, executor=self.executor,
            started_at=self.started_at, state=ExecutionState.FAILED,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "source_id": self.source_id,
            "executor": self.executor,
            "started_at": self.started_at.isoformat(),
            "state": self.state.value,
        }


@dataclass(frozen=True)
class ProductionReceipt:
    """Proof that a specific artifact was produced and validated.

    Every field is load-bearing. ``artifact_id`` says which artifact, the checksum
    says which bytes, and ``validation_result`` says they were checked. Removing any
    one of them turns the receipt back into a claim.
    """

    receipt_id: str
    run_id: str
    artifact_id: str
    artifact_checksum: str
    producer: str
    completed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    validation_result: ValidationResult | None = None

    def __post_init__(self) -> None:
        if not self.receipt_id:
            raise ValueError("PRODUCTION_RECEIPT_WITHOUT_ID:receipt_id required")
        if not self.run_id:
            raise ValueError(f"PRODUCTION_RECEIPT_WITHOUT_RUN:{self.receipt_id}")
        if not self.artifact_id:
            raise ValueError(
                f"PRODUCTION_RECEIPT_WITHOUT_ARTIFACT:{self.receipt_id}; a receipt "
                "with no artifact proves nothing"
            )
        if not self.producer:
            raise ValueError(f"PRODUCTION_RECEIPT_WITHOUT_PRODUCER:{self.receipt_id}")
        if not _SHA256_HEX.match(self.artifact_checksum or ""):
            raise ValueError(
                f"PRODUCTION_RECEIPT_BAD_CHECKSUM:{self.receipt_id}:"
                f"{self.artifact_checksum!r}; a receipt without a real digest is a claim"
            )
        if self.validation_result is None:
            raise ValueError(
                f"PRODUCTION_RECEIPT_WITHOUT_VALIDATION:{self.receipt_id}; an "
                "artifact that was never validated cannot be receipted"
            )
        if not self.validation_result.passed:
            failed = ", ".join(self.validation_result.names()) or "unnamed"
            raise ValueError(
                f"PRODUCTION_RECEIPT_WITH_FAILED_VALIDATION:{self.receipt_id}:{failed}"
            )
        if self.validation_result.observed_checksum != self.artifact_checksum:
            raise ValueError(
                f"PRODUCTION_RECEIPT_VALIDATION_MISMATCH:{self.receipt_id}; the "
                "validation observed different bytes than the receipt claims"
            )

    @property
    def identity(self) -> tuple[str, str]:
        """The uniqueness key: one run produces one receipt per artifact."""
        return (self.run_id, self.artifact_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "run_id": self.run_id,
            "artifact_id": self.artifact_id,
            "artifact_checksum": self.artifact_checksum,
            "producer": self.producer,
            "completed_at": self.completed_at.isoformat(),
            "validation_result": (
                self.validation_result.to_dict() if self.validation_result else None
            ),
        }


__all__ = [
    "ExecutionFailure",
    "ExecutionRun",
    "ExecutionState",
    "ProductionReceipt",
]
