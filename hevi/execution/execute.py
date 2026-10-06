"""HEVI P8.3 — Where a production receipt can and cannot be issued.

Everything in this module exists to make one shortcut impossible:

    artifact_exists()  !=  production_success

A path proves bytes were written. It does not prove they are playable, that they came
from the source we intended, or that a render finished rather than crashed after
flushing a partial file. So the receipt is not issued from a path — it is issued from
**bytes**, and only when a validator has observed those same bytes.

The gates, each refusing for its own reason:

    run                     -> SOURCE_MISSING
    executor                -> EXECUTOR_FAILED
    artifact bytes          -> ARTIFACT_MISSING / ARTIFACT_UNREADABLE
    digest over the bytes   -> PAYLOAD_MISMATCH
    validation              -> VALIDATION_NOT_RUN / VALIDATION_FAILED
    ledger                  -> ALREADY_RECEIPTED

Ordering is deliberate. A run that produced no artifact is not "validation failed",
and a receipt that already exists is not re-issued because the artifact still exists.
Collapsing these is how a re-run silently produces a second, contradictory receipt.

No subprocess, no filesystem and no renderer live here. This module decides what may be
claimed; performing the render is the executor's business. ``ArtifactReader`` is the
seam, so qualification can run without touching a disk.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from hevi.evidence.acquisition import checksum_bytes
from hevi.execution.models import (
    ExecutionFailure,
    ExecutionRun,
    ExecutionState,
    ProductionReceipt,
)
from hevi.validation.artifact import ValidationResult

#: Supplies an artifact's bytes. Injected so qualification needs no filesystem, and so
#: the transport stays the executor's concern rather than this module's.
ArtifactReader = Callable[[str], bytes]

#: Returns the validation result for an artifact. Also injected: a receipt must not be
#: able to validate on its own behalf.
Validator = Callable[[str, bytes], ValidationResult | None]


class ReceiptLedger:
    """Every receipt issued, enforcing one-per-(run, artifact).

    Bookkeeping, not authority. It cannot declare anything produced; it only refuses
    to hold two receipts that contradict each other for the same run and artifact.
    """

    def __init__(self) -> None:
        self._receipts: dict[tuple[str, str], ProductionReceipt] = {}
        self._receipt_ids: set[str] = set()

    def __len__(self) -> int:
        return len(self._receipts)

    def __contains__(self, identity: tuple[str, str]) -> bool:
        return identity in self._receipts

    def get(self, run_id: str, artifact_id: str) -> ProductionReceipt | None:
        return self._receipts.get((run_id, artifact_id))

    def receipts(self) -> tuple[ProductionReceipt, ...]:
        return tuple(self._receipts.values())

    def record(self, receipt: ProductionReceipt) -> ProductionReceipt:
        if receipt.receipt_id in self._receipt_ids:
            raise ValueError(f"DUPLICATE_RECEIPT_ID:{receipt.receipt_id}")
        if receipt.identity in self._receipts:
            existing = self._receipts[receipt.identity]
            raise ValueError(
                f"DUPLICATE_PRODUCTION_RECEIPT:run={receipt.run_id} "
                f"artifact={receipt.artifact_id} already receipted as "
                f"{existing.receipt_id}"
            )
        self._receipts[receipt.identity] = receipt
        self._receipt_ids.add(receipt.receipt_id)
        return receipt


def _refuse(
    run: ExecutionRun, failure: ExecutionFailure, reason: str
) -> tuple[ProductionReceipt | None, ExecutionFailure, str]:
    return None, failure, reason


def issue_receipt(
    run: ExecutionRun,
    *,
    source_id: str,
    artifact_id: str,
    read_artifact: ArtifactReader,
    validate: Validator,
    ledger: ReceiptLedger | None = None,
    receipt_id: str | None = None,
    producer: str | None = None,
    completed_at: datetime | None = None,
) -> tuple[ProductionReceipt | None, ExecutionFailure | None, str]:
    """Issue a production receipt, or explain why not.

    Returns ``(receipt, None, "")`` on success and ``(None, failure, reason)``
    otherwise, so a caller cannot read a receipt and a failure in the same result.
    """
    moment = completed_at or datetime.now(UTC)

    if run.state is not ExecutionState.COMPLETED:
        return _refuse(
            run, ExecutionFailure.EXECUTOR_FAILED,
            f"run state is {run.state.value}, not execution_completed",
        )
    if not source_id or run.source_id != source_id:
        return _refuse(
            run, ExecutionFailure.SOURCE_MISSING,
            "the acquired source for this run was not supplied",
        )
    if not artifact_id:
        return _refuse(run, ExecutionFailure.ARTIFACT_MISSING, "no artifact_id given")

    try:
        payload = read_artifact(artifact_id)
    except FileNotFoundError:
        return _refuse(
            run, ExecutionFailure.ARTIFACT_MISSING,
            f"artifact {artifact_id} does not exist",
        )
    except OSError as exc:
        return _refuse(
            run, ExecutionFailure.ARTIFACT_UNREADABLE,
            f"{type(exc).__name__}:{exc}",
        )

    if not payload:
        return _refuse(
            run, ExecutionFailure.ARTIFACT_MISSING,
            f"artifact {artifact_id} is empty",
        )

    digest = checksum_bytes(payload)

    validation = validate(artifact_id, payload)
    if validation is None:
        return _refuse(
            run, ExecutionFailure.VALIDATION_NOT_RUN,
            "the artifact was never validated",
        )
    if not validation.verify_payload(payload):
        return _refuse(
            run, ExecutionFailure.PAYLOAD_MISMATCH,
            "validation observed different bytes than the artifact contains",
        )
    if not validation.passed:
        failed = ", ".join(c.name for c in validation.failed_checks) or "unnamed"
        return _refuse(
            run, ExecutionFailure.VALIDATION_FAILED, f"failed checks: {failed}",
        )

    resolved_receipt_id = receipt_id or f"rc-{run.run_id}-{artifact_id}"
    if ledger is not None and (run.run_id, artifact_id) in ledger:
        existing = ledger.get(run.run_id, artifact_id)
        return _refuse(
            run, ExecutionFailure.ALREADY_RECEIPTED,
            f"already receipted as {existing.receipt_id if existing else 'unknown'}",
        )

    receipt = ProductionReceipt(
        receipt_id=resolved_receipt_id,
        run_id=run.run_id,
        artifact_id=artifact_id,
        artifact_checksum=digest,
        producer=producer or run.executor,
        completed_at=moment,
        validation_result=validation,
    )

    if ledger is not None:
        try:
            ledger.record(receipt)
        except ValueError as exc:
            return _refuse(run, ExecutionFailure.ALREADY_RECEIPTED, str(exc))

    return receipt, None, ""


__all__ = ["ArtifactReader", "ReceiptLedger", "Validator", "issue_receipt"]
