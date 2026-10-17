"""P0.3 — the atomic execution boundary.

Why rollback does not delete files
----------------------------------
§7 is the load-bearing decision in this module. A rollback has to answer, months later:

    was this artifact ever produced?
    why was it abandoned?
    which operation produced it?
    which provider produced it?
    why did the transaction roll back?

Deleting the output directory answers none of those and destroys the evidence. So
rollback restores *logical* state and marks what was produced but never committed as
``ORPHANED``. The bytes stay; the claim that they were part of the production goes
away. That is the difference between a rollback and an erasure.

State, not files, is what a transaction owns
---------------------------------------------
§6 forbids snapshotting only the filesystem. This snapshots the logical production
state: plan, timeline hash, operation statuses, provider assignments, artifact
references, render job states, receipt references, validation and repair state. The
snapshot is deliberately serialisable, so it can be persisted and survive a crash
(§58/§59) rather than living only in memory.

Fail-closed by construction
---------------------------
``rollback`` cannot be called before ``begin``, and ``commit`` cannot be called after
a rollback. Those are not runtime conveniences -- an ordering mistake here is the
difference between a production that is marked committed and one that is not, which is
the single most consequential field in the system.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from hevi.production.execution_result import ExecutionFailureRecord, ProductionExecutionResult
from hevi.production.operation import ProductionOperation, resolve_execution_order


class TransactionState(StrEnum):
    """§5 lifecycle.

    ``OPEN`` and ``RUNNING`` are separate because a transaction that was created but
    never started is a different fact from one that began executing: the first has
    changed nothing, the second has materialised artifacts that may need orphaning.
    """

    OPEN = "OPEN"
    RUNNING = "RUNNING"
    COMMITTING = "COMMITTING"
    COMMITTED = "COMMITTED"
    ROLLING_BACK = "ROLLING_BACK"
    ROLLED_BACK = "ROLLED_BACK"
    FAILED = "FAILED"


_TERMINAL = frozenset(
    {TransactionState.COMMITTED, TransactionState.ROLLED_BACK, TransactionState.FAILED}
)

#: Legal transitions. A transaction that skips COMMITTING cannot be COMMITTED, and one
#: that reaches a terminal state cannot leave it -- except COMMITTED -> ROLLING_BACK,
#: which is not legal either. Reopening a committed transaction would silently
#: invalidate receipts that were already handed out.
_TRANSITIONS: dict[TransactionState, frozenset[TransactionState]] = {
    TransactionState.OPEN: frozenset({TransactionState.RUNNING, TransactionState.FAILED}),
    TransactionState.RUNNING: frozenset(
        {TransactionState.COMMITTING, TransactionState.ROLLING_BACK, TransactionState.FAILED}
    ),
    TransactionState.COMMITTING: frozenset(
        {TransactionState.COMMITTED, TransactionState.ROLLING_BACK}
    ),
    TransactionState.ROLLING_BACK: frozenset(
        {TransactionState.ROLLED_BACK, TransactionState.FAILED}
    ),
    TransactionState.COMMITTED: frozenset(),
    TransactionState.ROLLED_BACK: frozenset(),
    TransactionState.FAILED: frozenset(),
}


class ArtifactState(StrEnum):
    """§7 lifecycle.

    ``ORPHANED`` is the state this whole module exists to produce. An orphan is a real
    artifact whose transaction never committed -- it exists, and nothing claims it.
    """

    PLANNED = "PLANNED"
    MATERIALIZING = "MATERIALIZING"
    MATERIALIZED = "MATERIALIZED"
    VALIDATED = "VALIDATED"
    COMMITTED = "COMMITTED"
    ORPHANED = "ORPHANED"
    INVALID = "INVALID"


@dataclass(frozen=True)
class ArtifactStateRecord:
    """One artifact as the transaction sees it."""

    artifact_id: str
    content_hash: str
    kind: str
    uri: str
    state: ArtifactState = ArtifactState.PLANNED
    produced_by_operation: str = ""
    producer_provider: str = ""
    receipt_ref: str = ""
    orphaned_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "content_hash": self.content_hash,
            "kind": self.kind,
            "uri": self.uri,
            "state": self.state.value,
            "produced_by_operation": self.produced_by_operation,
            "producer_provider": self.producer_provider,
            "receipt_ref": self.receipt_ref,
            "orphaned_reason": self.orphaned_reason,
        }


class TransactionSnapshot(BaseModel):
    """§6. Logical production state, not filesystem state.

    Every field is here because every field would otherwise survive a rollback that
    should have undone it. A snapshot missing ``provider_assignments`` would leave a
    rolled-back production still claiming it ran on a paid provider.
    """

    model_config = ConfigDict(frozen=True)

    production_id: str
    plan_ref: str = ""
    timeline_hash: str = ""
    operation_states: dict[str, str] = Field(default_factory=dict)
    provider_assignments: dict[str, str] = Field(default_factory=dict)
    artifact_references: dict[str, str] = Field(default_factory=dict)
    render_job_states: dict[str, str] = Field(default_factory=dict)
    receipt_references: tuple[str, ...] = ()
    validation_state: str = "NOT_RUN"
    repair_state: str = "NONE"

    def digest(self) -> str:
        """Stable identity for the snapshot.

        Lets a resumed process prove it restored the same logical state it began with
        (§58), rather than assuming so.
        """
        payload = self.model_dump_json()
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TransactionReceipt(BaseModel):
    """Proof a transaction committed. Immutable."""

    model_config = ConfigDict(frozen=True)

    transaction_id: str
    production_id: str
    snapshot_digest: str
    committed_operation_ids: tuple[str, ...]
    artifact_ids: tuple[str, ...]
    receipt_refs: tuple[str, ...] = ()
    #: §36: failures that did not block the commit -- optional operations only. On the
    #: receipt so an optional failure is reported downstream instead of disappearing at
    #: commit time.
    tolerated_failures: tuple[str, ...] = ()
    committed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RollbackReceipt(BaseModel):
    """Proof a transaction rolled back, and what that orphaned.

    Retained forever alongside receipts (§7). This is the document that answers
    "why was this artifact abandoned".
    """

    model_config = ConfigDict(frozen=True)

    transaction_id: str
    production_id: str
    reason: str
    snapshot_digest: str
    restored_operation_ids: tuple[str, ...]
    orphaned_artifact_ids: tuple[str, ...]
    retained_receipt_refs: tuple[str, ...]
    rolled_back_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TransactionError(RuntimeError):
    """Raised on an illegal transaction transition."""


class ProductionExecutionTransaction:
    """One atomic logical unit of production execution.

    Not a Protocol: the spec sketches the shape as a Protocol, but an implementation
    with invariants this many cannot be usefully substituted. The three methods the
    spec names -- ``begin``/``commit``/``rollback`` -- are the public surface.
    """

    def __init__(self, *, production_id: str, operations: tuple[ProductionOperation, ...] = (),
                 timeline_hash: str = "") -> None:
        if not production_id:
            raise ValueError("TRANSACTION_WITHOUT_PRODUCTION_ID")
        self.production_id = production_id
        self.operations = operations
        self._state = TransactionState.OPEN
        self._snapshot: TransactionSnapshot | None = None
        self._ordered = resolve_execution_order(operations) if operations else ()
        self._artifacts: dict[str, ArtifactStateRecord] = {}
        self._operation_states: dict[str, str] = {op.operation_id: "PENDING" for op in operations}
        self._provider_assignments: dict[str, str] = {}
        self._results: list[ProductionExecutionResult] = []
        self._failures: list[ExecutionFailureRecord] = []
        self._receipt_refs: list[str] = []
        #: Artifacts committed by *earlier* transactions. Rollback must not touch
        #: these: they are production output, not this transaction's output.
        self._preexisting_committed: set[str] = set()

    # ── inspection ──

    @property
    def transaction_id(self) -> str:
        if self._snapshot is None:
            return f"tx-{hashlib.sha256(self.production_id.encode()).hexdigest()[:16]}"
        return f"tx-{self._snapshot.digest()[:16]}"

    @property
    def state(self) -> TransactionState:
        return self._state

    @property
    def failures(self) -> tuple[ExecutionFailureRecord, ...]:
        return tuple(self._failures)

    @property
    def results(self) -> tuple[ProductionExecutionResult, ...]:
        return tuple(self._results)

    def artifact(self, artifact_id: str) -> ArtifactStateRecord | None:
        return self._artifacts.get(artifact_id)

    def artifacts_in_state(self, state: ArtifactState) -> tuple[str, ...]:
        return tuple(
            sorted(a.artifact_id for a in self._artifacts.values() if a.state is state)
        )

    def mark_preexisting_committed(self, artifact_ids: set[str]) -> None:
        """Register artifacts committed before this transaction began.

        Without this, a rollback would orphan a previous production's final deliverable
        simply because a later transaction touched the same production.
        """
        self._preexisting_committed |= set(artifact_ids)

    # ── state machine ──

    def _transition(self, target: TransactionState) -> None:
        allowed = _TRANSITIONS[self._state]
        if target not in allowed:
            raise TransactionError(
                f"ILLEGAL_TRANSACTION_TRANSITION:{self._state.value}->{target.value}"
            )
        self._state = target

    def begin(self) -> TransactionSnapshot:
        """Snapshot logical state and open for execution."""
        if self._state in _TERMINAL:
            raise TransactionError(f"TRANSACTION_ALREADY_TERMINAL:{self._state.value}")
        self._snapshot = self._capture()
        self._transition(TransactionState.RUNNING)
        return self._snapshot

    def _capture(self) -> TransactionSnapshot:
        return TransactionSnapshot(
            production_id=self.production_id,
            timeline_hash=self._snapshot.timeline_hash if self._snapshot else "",
            operation_states=dict(self._operation_states),
            provider_assignments=dict(self._provider_assignments),
            artifact_references={a.artifact_id: a.uri for a in self._artifacts.values()},
            render_job_states={},
            receipt_references=tuple(self._receipt_refs),
        )

    # ── execution recording ──

    def record_artifact(
        self,
        *,
        artifact_id: str,
        content_hash: str,
        kind: str,
        uri: str,
        operation_id: str,
        provider_ref: str = "",
        receipt_ref: str = "",
    ) -> ArtifactStateRecord:
        """Record a materialised artifact.

        Refuses to overwrite an artifact that is already ``COMMITTED``. Silently
        replacing committed content would leave a receipt pointing at bytes that no
        longer exist.
        """
        existing = self._artifacts.get(artifact_id)
        if existing is not None and existing.state is ArtifactState.COMMITTED:
            raise TransactionError(
                f"ARTIFACT_ALREADY_COMMITTED:{artifact_id}; committed artifacts are "
                "immutable within a transaction"
            )
        record = ArtifactStateRecord(
            artifact_id=artifact_id,
            content_hash=content_hash,
            kind=kind,
            uri=uri,
            state=ArtifactState.MATERIALIZED,
            produced_by_operation=operation_id,
            producer_provider=provider_ref,
            receipt_ref=receipt_ref,
        )
        self._artifacts[artifact_id] = record
        if receipt_ref and receipt_ref not in self._receipt_refs:
            # The transaction has to *know* about the receipt, not just the artifact
            # row that mentions it. Rollback retains receipts (§7), and retention needs
            # something to retain -- an artifact-local reference is not a receipt index.
            self._receipt_refs.append(receipt_ref)
        return record

    def record_result(self, result: ProductionExecutionResult) -> None:
        self._results.append(result)
        self._operation_states[result.operation_id] = result.status

    def record_failure(self, failure: ExecutionFailureRecord) -> None:
        """Record a failure. §35: there is no path that discards one."""
        self._failures.append(failure)
        if failure.operation_id:
            self._operation_states[failure.operation_id] = "FAILED"

    def assign_provider(self, operation_id: str, provider_ref: str) -> None:
        self._provider_assignments[operation_id] = provider_ref

    # ── completion ──

    def _required_operation_ids(self) -> set[str]:
        return {op.operation_id for op in self.operations if op.required}

    def _blocking_failures(self) -> list[ExecutionFailureRecord]:
        """Failures belonging to required operations, plus unoperationed ones.

        A failure with no ``operation_id`` is blocking by default: it happened during
        the transaction and cannot be attributed to something declared optional, so
        assuming it was benign would be the unsafe reading.
        """
        required = self._required_operation_ids()
        return [
            failure
            for failure in self._failures
            if failure.operation_id is None or failure.operation_id in required
        ]

    def commit(self) -> TransactionReceipt:
        """§8/§36. Commit once running, unless a *required* operation failed.

        Two rules pull against each other here and the resolution matters:

        * §35 — an operation that failed must never be silently passed over.
        * §36 — an operation declaring ``required=False`` may fail without blocking.

        So commit refuses when a **required** operation has a recorded failure, and
        permits commit when only optional ones failed. Nothing is lost either way: the
        failure records stay attached to the transaction and are carried on the receipt,
        so an optional failure is reported rather than swallowed.

        An earlier version refused on *any* failure, which made §36 unimplementable --
        the only way past it would have been for the caller to drop the failure record,
        which is exactly the silent failure §35 forbids.
        """
        if self._state is TransactionState.RUNNING:
            blocking = self._blocking_failures()
            if blocking:
                raise TransactionError(
                    f"TRANSACTION_HAS_REQUIRED_FAILURES:{len(blocking)};"
                    f"{sorted(f.operation_id or '?' for f in blocking)}; roll back "
                    "instead of committing a run that failed"
                )
            self._transition(TransactionState.COMMITTING)
        if self._state is not TransactionState.COMMITTING:
            raise TransactionError(f"CANNOT_COMMIT_FROM:{self._state.value}")

        for record in self._artifacts.values():
            if record.state in (ArtifactState.MATERIALIZED, ArtifactState.VALIDATED):
                self._artifacts[record.artifact_id] = replace(
                    record, state=ArtifactState.COMMITTED
                )
        self._transition(TransactionState.COMMITTED)

        committed_ops = tuple(
            op.operation_id for op in self._ordered if self._operation_states.get(op.operation_id) == "SUCCEEDED"
        )
        return TransactionReceipt(
            transaction_id=self.transaction_id,
            production_id=self.production_id,
            snapshot_digest=self._snapshot.digest() if self._snapshot else "",
            committed_operation_ids=committed_ops,
            artifact_ids=self.artifacts_in_state(ArtifactState.COMMITTED),
            receipt_refs=tuple(self._receipt_refs),
            tolerated_failures=tuple(
                failure.failure_id for failure in self._failures
            ),
        )

    def rollback(self, reason: str) -> RollbackReceipt:
        """§7/§8. Restore logical state; orphan uncommitted artifacts; keep receipts.

        Never deletes bytes. Committed artifacts are untouched; new uncommitted ones
        become ``ORPHANED`` with the reason recorded; receipts and failure records are
        retained so the outcome is auditable.
        """
        if self._state in (TransactionState.COMMITTED, TransactionState.ROLLED_BACK):
            raise TransactionError(f"CANNOT_ROLLBACK_FROM:{self._state.value}")
        if self._state is TransactionState.RUNNING:
            self._transition(TransactionState.ROLLING_BACK)

        orphaned: list[str] = []
        for record in list(self._artifacts.values()):
            if record.state is ArtifactState.COMMITTED:
                continue
            if record.artifact_id in self._preexisting_committed:
                continue
            self._artifacts[record.artifact_id] = replace(
                record, state=ArtifactState.ORPHANED, orphaned_reason=reason
            )
            orphaned.append(record.artifact_id)

        if self._snapshot is not None:
            self._operation_states = dict(self._snapshot.operation_states)
            self._provider_assignments = dict(self._snapshot.provider_assignments)

        self._transition(TransactionState.ROLLED_BACK)
        return RollbackReceipt(
            transaction_id=self.transaction_id,
            production_id=self.production_id,
            reason=reason,
            snapshot_digest=self._snapshot.digest() if self._snapshot else "",
            restored_operation_ids=tuple(self._operation_states),
            orphaned_artifact_ids=tuple(sorted(orphaned)),
            # Receipts are evidence, not state. Retained deliberately (§7).
            retained_receipt_refs=tuple(self._receipt_refs),
        )


__all__ = [
    "ArtifactState",
    "ArtifactStateRecord",
    "ProductionExecutionTransaction",
    "RollbackReceipt",
    "TransactionError",
    "TransactionReceipt",
    "TransactionSnapshot",
    "TransactionState",
]
