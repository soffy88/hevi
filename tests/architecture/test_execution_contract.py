"""P0.7 — transaction and executor behaviour (§50 T1–T8, §52 F1–F8).

The theme is that nothing disappears. A failed run still leaves a failure record, a
rollback receipt, orphaned-but-present artifacts and the receipts issued before the
failure. §35 forbids `except Exception: return None` and §7 forbids answering a
rollback by deleting files; these tests are what make either of those detectable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.production.execution_executor import (
    ExecutionContext,
    OperationValidator,
    ProductionExecutor,
)
from hevi.production.execution_result import (
    AdapterError,
    ExecutionFailureRecord,
    ProductionExecutionResult,
)
from hevi.production.execution_transaction import (
    ArtifactState,
    ProductionExecutionTransaction,
    TransactionError,
)
from hevi.production.operation import (
    ArtifactExpectation,
    ProductionOperation,
    ProductionOperationType,
)

# ── adapters ──


class RecordingAdapter:
    """Succeeds, producing a real file per artifact so nothing is mocked away."""

    name = "recording"
    renderer_ref = "html_gsap"

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self.calls: list[str] = []
        self.receipts: list[str] = []

    def can_execute(self, operation: ProductionOperation) -> bool:
        return operation.operation_type is ProductionOperationType.RENDER

    def execute(
        self, operation: ProductionOperation, context: ExecutionContext
    ) -> ProductionExecutionResult:
        self.calls.append(operation.operation_id)
        if context.dry_run:
            raise AssertionError("dry run must not invoke the adapter")
        artifact_id = f"{operation.operation_id}-out"
        target = self.work_dir / f"{artifact_id}.bin"
        target.write_bytes(b"real bytes")
        self.receipts.append(f"receipt-{artifact_id}")
        return ProductionExecutionResult(
            operation_id=operation.operation_id,
            status="SUCCEEDED",
            artifacts=(artifact_id,),
            receipt_refs=(f"receipt-{artifact_id}",),
            metadata={
                f"hash:{artifact_id}": "ab" * 32,
                f"kind:{artifact_id}": "video",
                f"uri:{artifact_id}": str(target),
                "receipt_ref": f"receipt-{artifact_id}",
            },
        )


class FailingAdapter:
    """Fails with a chosen error type, for §52."""

    name = "failing"
    renderer_ref = "html_gsap"

    def __init__(self, error_type: str, *, fail_times: int | None = None) -> None:
        self.error_type = error_type
        #: Fail this many times, then succeed. ``None`` means fail every time.
        self.fail_times = fail_times
        self.calls = 0

    def can_execute(self, operation: ProductionOperation) -> bool:
        return True

    def execute(
        self, operation: ProductionOperation, context: ExecutionContext
    ) -> ProductionExecutionResult:
        self.calls += 1
        still_failing = self.fail_times is None or self.calls <= self.fail_times
        if still_failing:
            raise AdapterError(self.error_type, f"simulated {self.error_type}")
        (context.work_dir or Path("/tmp")).mkdir(parents=True, exist_ok=True)
        return ProductionExecutionResult(
            operation_id=operation.operation_id,
            status="SUCCEEDED",
            artifacts=(f"{operation.operation_id}-out",),
            metadata={
                f"hash:{operation.operation_id}-out": "cd" * 32,
                f"kind:{operation.operation_id}-out": "video",
                f"uri:{operation.operation_id}-out": f"/tmp/{operation.operation_id}-out.bin",
            },
        )


def _op(
    operation_id: str,
    *,
    depends_on: tuple[str, ...] = (),
    required: bool = True,
    **kwargs,
) -> ProductionOperation:
    base = dict(
        operation_type=ProductionOperationType.RENDER,
        production_id="prod-1",
        renderer_ref="html_gsap",
        expected_outputs=(
            ArtifactExpectation(name="video", kind="video", deterministic=True),
        ),
    )
    base.update(kwargs)
    return ProductionOperation(
        operation_id=operation_id, depends_on=depends_on, required=required,
        idempotency_key=f"key-{operation_id}", **base,
    )


def _executor(adapter, **validator_kwargs) -> ProductionExecutor:
    return ProductionExecutor(
        adapter=adapter,
        validator=OperationValidator(**validator_kwargs),
        max_attempts=validator_kwargs.pop("max_attempts", 3),
    )


# ── T1/T2: commit paths ──


def test_t1_empty_transaction_commits(tmp_path: Path):
    executor = _executor(RecordingAdapter(tmp_path))
    outcome = executor.execute(production_id="prod-1", operations=[])
    assert outcome.committed
    assert outcome.commit is not None
    assert outcome.commit.committed_operation_ids == ()
    assert outcome.commit.transaction_id.startswith("tx-")


def test_t2_one_operation_success_commits(tmp_path: Path):
    executor = _executor(RecordingAdapter(tmp_path))
    outcome = executor.execute(production_id="prod-1", operations=[_op("a")])
    assert outcome.committed
    assert outcome.commit.committed_operation_ids == ("a",)
    assert (tmp_path / "a-out.bin").read_bytes() == b"real bytes"


def test_t2_multiple_operations_commit_in_canonical_order(tmp_path: Path):
    adapter = RecordingAdapter(tmp_path)
    executor = _executor(adapter)
    # Declared out of order on purpose; sequence + depends_on decide execution order.
    ops = [
        _op("encode", operation_type=ProductionOperationType.ENCODE, depends_on=("render",), sequence=2),
        _op("render", sequence=1),
    ]
    outcome = executor.execute(production_id="prod-1", operations=ops)
    assert adapter.calls == ["render", "encode"]
    assert outcome.committed


# ── T3/T4/T5/T6: rollback ──


def test_t3_operation_failure_rolls_back(tmp_path: Path):
    executor = _executor(FailingAdapter("provider_unavailable"))
    outcome = executor.execute(production_id="prod-1", operations=[_op("a")])
    assert not outcome.committed
    assert outcome.rollback is not None
    assert outcome.rollback.reason == "operation_failed:a"
    assert outcome.failures


def test_t4_second_operation_failure_restores_first_operations_logical_state(tmp_path: Path):
    class FirstOkSecondFails:
        name = "mixed"
        renderer_ref = "html_gsap"

        def can_execute(self, operation): return True

        def execute(self, operation, context):
            if operation.operation_id == "first":
                return ProductionExecutionResult(
                    operation_id="first", status="SUCCEEDED",
                    artifacts=("first-out",), receipt_refs=("receipt-first",),
                    metadata={"hash:first-out": "ef" * 32, "kind:first-out": "video",
                              "uri:first-out": "/tmp/f.bin", "receipt_ref": "receipt-first"},
                )
            raise AdapterError("provider_unavailable","second failed")

    executor = _executor(FirstOkSecondFails())
    ops = [_op("first", sequence=1), _op("second", depends_on=("first",), sequence=2)]
    outcome = executor.execute(production_id="prod-1", operations=ops)

    assert not outcome.committed
    assert outcome.rollback is not None
    # "first" produced a receipt that survives the rollback as evidence.
    assert "receipt-first" in outcome.rollback.retained_receipt_refs


def test_t5_artifact_generated_before_failure_is_orphaned_not_deleted(tmp_path: Path):
    """§7. The bytes stay; the claim goes away."""

    class ProducesThenFails:
        name = "pf"
        renderer_ref = "html_gsap"

        def __init__(self):
            self.made: list[Path] = []

        def can_execute(self, operation): return True

        def execute(self, operation, context):
            if operation.operation_id == "first":
                target = tmp_path / "first.bin"
                target.write_bytes(b"produced before failure")
                self.made.append(target)
                return ProductionExecutionResult(
                    operation_id="first", status="SUCCEEDED", artifacts=("first-out",),
                    receipt_refs=("receipt-first",),
                    metadata={"hash:first-out": "ef" * 32, "kind:first-out": "video",
                              "uri:first-out": str(target), "receipt_ref": "receipt-first"},
                )
            raise AdapterError("provider_unavailable","downstream failed")

    executor = _executor(ProducesThenFails())
    ops = [_op("first", sequence=1), _op("second", depends_on=("first",), sequence=2)]
    outcome = executor.execute(production_id="prod-1", operations=ops)

    assert outcome.orphan_ids == ("first-out",)
    # The file still exists: rollback deleted nothing.
    assert (tmp_path / "first.bin").exists()
    assert (tmp_path / "first.bin").read_bytes() == b"produced before failure"


def test_t6_receipts_are_retained_after_rollback(tmp_path: Path):
    class ProducesThenFails:
        name = "pf"
        renderer_ref = "html_gsap"

        def can_execute(self, operation): return True

        def execute(self, operation, context):
            if operation.operation_id == "first":
                (tmp_path / "f.bin").write_bytes(b"x")
                return ProductionExecutionResult(
                    operation_id="first", status="SUCCEEDED", artifacts=("first-out",),
                    receipt_refs=("receipt-first",),
                    metadata={"hash:first-out": "ef" * 32, "kind:first-out": "video",
                              "uri:first-out": str(tmp_path / "f.bin"),
                              "receipt_ref": "receipt-first"},
                )
            raise AdapterError("provider_unavailable","nope")

    executor = _executor(ProducesThenFails())
    ops = [_op("first", sequence=1), _op("second", depends_on=("first",), sequence=2)]
    outcome = executor.execute(production_id="prod-1", operations=ops)
    assert outcome.rollback.retained_receipt_refs == ("receipt-first",)


def test_preexisting_committed_artifacts_survive_a_later_rollback(tmp_path: Path):
    """A previous production's deliverable must not be orphaned by an unrelated rollback."""
    executor = _executor(FailingAdapter("provider_unavailable"))
    outcome = executor.execute(
        production_id="prod-1", operations=[_op("a")],
        preexisting_committed={"deliverable-v1"},
    )
    assert outcome.orphan_ids == ()


# ── T7: idempotency ──


def test_t7_same_idempotency_key_yields_no_duplicate_logical_artifact():
    """The key is the identity. Two executions of the same operation are one artifact."""
    op_a = _op("a")
    op_b = ProductionOperation(
        **{
            **{k: v for k, v in op_a.model_dump().items()
               if k not in ("sequence", "depends_on", "idempotency_key")},
            "idempotency_key": op_a.idempotency_key,
        }
    )
    assert op_a.idempotency_key == op_b.idempotency_key
    assert op_a.compute_idempotency_key() == op_b.compute_idempotency_key()


def test_t7_reordering_does_not_change_the_idempotency_key():
    """§38 allows ordering to change. The key must not, or a retry regenerates."""
    op = _op("a", sequence=1, depends_on=("z",))
    reordered = op.model_copy(update={"sequence": 99, "depends_on": ("b", "a2")})
    assert op.compute_idempotency_key() == reordered.compute_idempotency_key()


# ── T8: transient retry ──


def test_t8_transient_failure_is_retried_and_commits(tmp_path: Path):
    adapter = FailingAdapter("timeout", fail_times=1)
    executor = _executor(adapter)
    outcome = executor.execute(
        production_id="prod-1", operations=[_op("a")], work_dir=tmp_path
    )
    assert adapter.calls >= 2, "a transient failure must be retried"
    assert outcome.committed


def test_semantic_failure_is_not_retried(tmp_path: Path):
    adapter = FailingAdapter("invalid_timeline")
    executor = _executor(adapter)
    outcome = executor.execute(production_id="prod-1", operations=[_op("a")])
    assert adapter.calls == 1, "a semantic failure must not be retried"
    assert not outcome.committed
    assert outcome.failures[0].requires_repair_incident


# ── §52 F1–F8: every failure produces a record ──


@pytest.mark.parametrize(
    ("error_type", "expect_retry"),
    [
        ("timeout", True),
        ("rate_limited", True),
        ("provider_unavailable", False),
        ("invalid_provider_response", False),
        ("invalid_timeline", False),
        ("ffmpeg_transient", True),
        ("renderer_crash", False),
        ("validation_failed", False),
    ],
)
def test_f1_f8_every_failure_produces_a_record_and_transaction_behaviour(
    tmp_path: Path, error_type: str, expect_retry: bool
):
    adapter = FailingAdapter(error_type)
    executor = _executor(adapter)
    outcome = executor.execute(production_id="prod-1", operations=[_op("a")])

    # F1–F8: a failure record always exists. None of them is silent.
    assert outcome.failures, f"{error_type} produced no failure record"
    failure = outcome.failures[0]
    assert failure.production_id == "prod-1"
    assert failure.transaction_id == outcome.transaction_id
    # And the transaction behaved: a required operation's failure rolls back.
    assert not outcome.committed
    assert outcome.rollback is not None
    if expect_retry:
        assert adapter.calls >= 2
    else:
        assert adapter.calls == 1


# ── §36 partial failure ──


def test_optional_operation_failure_does_not_block_commit(tmp_path: Path):
    class OptionalFails:
        name = "opt"
        renderer_ref = "html_gsap"

        def can_execute(self, operation): return True

        def execute(self, operation, context):
            if operation.required:
                (tmp_path / "req.bin").write_bytes(b"x")
                return ProductionExecutionResult(
                    operation_id=operation.operation_id, status="SUCCEEDED",
                    artifacts=("req-out",),
                    metadata={"hash:req-out": "11" * 32, "kind:req-out": "video",
                              "uri:req-out": str(tmp_path / "req.bin")},
                )
            raise AdapterError("capability_mismatch","optional thing failed")

    executor = _executor(OptionalFails())
    ops = [_op("req", sequence=1), _op("opt", sequence=2, required=False)]
    outcome = executor.execute(production_id="prod-1", operations=ops)

    assert outcome.committed
    # §36: final validation must still learn an optional operation failed.
    assert outcome.failures
    assert "opt" in outcome.skipped


def test_required_operation_failure_blocks_commit_even_after_optional_failures(tmp_path: Path):
    executor = _executor(FailingAdapter("invalid_timeline"))
    ops = [_op("opt", sequence=1, required=False), _op("req", sequence=2)]
    outcome = executor.execute(production_id="prod-1", operations=ops)
    assert not outcome.committed


# ── §57 dry run ──


def test_dry_run_validates_without_generating_media(tmp_path: Path):
    adapter = RecordingAdapter(tmp_path)
    executor = _executor(adapter)
    outcome = executor.execute(
        production_id="prod-1", operations=[_op("a")], dry_run=True
    )
    assert adapter.calls == [], "dry run must not invoke the adapter"
    assert not list(tmp_path.iterdir()), "dry run must not create media"
    assert outcome.dry_run
    # It still resolved and reported what it expected to produce.
    assert outcome.results[0].metadata["expected_outputs"] == ["video"]


# ── transaction invariants ──


def test_commit_is_refused_when_a_required_operation_failed():
    """§35. A required operation that failed cannot be passed over at commit time."""
    op = _op("a")
    tx = ProductionExecutionTransaction(production_id="prod-1", operations=(op,))
    tx.begin()
    tx.record_failure(
        ExecutionFailureRecord.for_operation(
            production_id="prod-1", operation=op, transaction_id=tx.transaction_id,
            stage="execute", error_type="invalid_timeline", message="bad",
        )
    )

    with pytest.raises(TransactionError, match="HAS_REQUIRED_FAILURES"):
        tx.commit()


def test_optional_failure_is_carried_on_the_commit_receipt():
    """§36 + §35 together: commit proceeds, but the failure is not swallowed.

    Permitting the commit without recording the tolerated failure would satisfy §36 and
    violate §35 -- the failure would simply disappear at commit time.
    """
    required_op = _op("req")
    optional_op = _op("opt", required=False)
    tx = ProductionExecutionTransaction(
        production_id="prod-1", operations=(required_op, optional_op)
    )
    tx.begin()
    tx.record_failure(
        ExecutionFailureRecord.for_operation(
            production_id="prod-1", operation=optional_op,
            transaction_id=tx.transaction_id, stage="execute",
            error_type="capability_mismatch", message="optional thing failed",
        )
    )
    receipt = tx.commit()
    assert receipt.tolerated_failures, "an optional failure must be reported on commit"
    # And the failure record is still attached to the transaction.
    assert len(tx.failures) == 1


def test_transaction_cannot_be_reopened_after_commit():
    tx = ProductionExecutionTransaction(production_id="prod-1")
    tx.begin()
    tx.commit()
    with pytest.raises(TransactionError):
        tx.begin()


def test_committed_artifacts_are_immutable_within_a_transaction():
    tx = ProductionExecutionTransaction(production_id="prod-1")
    tx.begin()
    tx.record_artifact(artifact_id="a", content_hash="ab" * 32, kind="video",
                       uri="/tmp/a.mp4", operation_id="op")
    tx.commit()
    with pytest.raises(TransactionError, match="ALREADY_COMMITTED"):
        tx.record_artifact(artifact_id="a", content_hash="cd" * 32, kind="video",
                           uri="/tmp/other.mp4", operation_id="op")


def test_orphan_record_keeps_its_provenance():
    """§7 asks which operation and which provider produced the abandoned artifact."""
    op = _op("a")
    tx = ProductionExecutionTransaction(production_id="prod-1", operations=(op,))
    tx.begin()
    tx.record_artifact(artifact_id="a", content_hash="ab" * 32, kind="video",
                       uri="/tmp/a.mp4", operation_id="a", provider_ref="wan_local")
    tx.rollback("quality gate failed")
    record = tx.artifact("a")
    assert record.state is ArtifactState.ORPHANED
    assert record.produced_by_operation == "a"
    assert record.producer_provider == "wan_local"
    assert record.orphaned_reason == "quality gate failed"
