"""P8.3 — Execution proof, and the three shortcuts it refuses.

    artifact_exists()  !=  production_success

A file on disk proves bytes were written. It does not prove they are playable, that
they came from the source we intended, or that a render finished rather than crashed
after flushing a partial file. So a receipt is issued from **bytes** — never from a
path — and only when a validator has observed those same bytes.

A naming collision is resolved here rather than reproduced. P6 already defines
``ExecutionReceipt`` meaning *a delegate ran*. P8.3 needs proof that an *artifact was
produced and validated*, which is a different fact about a different subject. Defining
a second ``ExecutionReceipt`` would put two meanings behind one name — the same defect
P8.2 found in ``AcquisitionState.FAILED`` colliding with ``RunState.failed`` — and
would breach ``NO_SECOND_PRODUCTION_AUTHORITY``. Hence :class:`ProductionReceipt`.

T1-T5 below are the five ways this collapses in practice.
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib

import pytest

from hevi.evidence.acquisition import checksum_bytes
from hevi.execution import (
    ExecutionFailure,
    ExecutionRun,
    ExecutionState,
    ProductionReceipt,
    ReceiptLedger,
    issue_receipt,
)
from hevi.production.p6.production_runtime import RunState
from hevi.validation import ValidationCheck, ValidationResult

EXEC_DIR = pathlib.Path("hevi/execution")
MODELS = EXEC_DIR / "models.py"
EXECUTE = EXEC_DIR / "execute.py"
VALIDATION = pathlib.Path("hevi/validation/artifact.py")

BYTES = b"a real rendered video"
CHECKSUM = checksum_bytes(BYTES)


def _validator(passed: bool = True, payload: bytes = BYTES, name: str = "decode"):
    def _inner(artifact_id: str, body: bytes) -> ValidationResult:
        return ValidationResult(
            "ffprobe",
            (ValidationCheck("container", observed=True, expected=True), ValidationCheck(name, observed=passed, expected=True)),
            observed_checksum=checksum_bytes(payload),
        )

    return _inner


def _completed(source_id: str = "src1") -> ExecutionRun:
    return ExecutionRun("run1", source_id, "render@v1").completed()


def _issue(run=None, *, artifact_id="art1", reader=None, validator=None, ledger=None,
           source_id="src1", run_source_id=None, **kwargs):
    return issue_receipt(
        run if run is not None else _completed(run_source_id or source_id),
        source_id=source_id,
        artifact_id=artifact_id,
        read_artifact=reader if reader is not None else (lambda a: BYTES),
        validate=validator if validator is not None else _validator(),
        ledger=ledger if ledger is not None else ReceiptLedger(),
        **kwargs,
    )


def _receipt() -> ProductionReceipt:
    validation = ValidationResult(
        "ffprobe", (ValidationCheck("decode", observed=True, expected=True),), observed_checksum=CHECKSUM
    )
    return ProductionReceipt(
        receipt_id="rc1", run_id="run1", artifact_id="art1",
        artifact_checksum=CHECKSUM, producer="render@v1", validation_result=validation,
    )


def _code_identifiers(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return (
        {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    )


# ══════════════════════════════════════════════════════════════════════════
# the receipt is not forgeable by hand
# ══════════════════════════════════════════════════════════════════════════


def test_production_receipt_has_exactly_the_specified_fields():
    names = {f.name for f in dataclasses.fields(ProductionReceipt)}
    assert names == {
        "receipt_id", "run_id", "artifact_id", "artifact_checksum",
        "producer", "completed_at", "validation_result",
    }


def test_receipt_requires_an_artifact_id():
    with pytest.raises(ValueError, match="PRODUCTION_RECEIPT_WITHOUT_ARTIFACT"):
        ProductionReceipt(
            receipt_id="rc1", run_id="run1", artifact_id="",
            artifact_checksum=CHECKSUM, producer="p",
            validation_result=_receipt().validation_result,
        )


def test_receipt_requires_a_real_checksum():
    """T2: a receipt without a digest is a claim about bytes it never saw."""
    for bad in (None, "", "TODO", "0" * 63, "A" * 64):
        with pytest.raises(ValueError, match="PRODUCTION_RECEIPT_BAD_CHECKSUM"):
            ProductionReceipt(
                receipt_id="rc1", run_id="run1", artifact_id="art1",
                artifact_checksum=bad, producer="p",
                validation_result=_receipt().validation_result,
            )


def test_receipt_requires_validation():
    with pytest.raises(ValueError, match="PRODUCTION_RECEIPT_WITHOUT_VALIDATION"):
        ProductionReceipt(
            receipt_id="rc1", run_id="run1", artifact_id="art1",
            artifact_checksum=CHECKSUM, producer="p", validation_result=None,
        )


def test_receipt_refuses_failed_validation():
    validation = ValidationResult(
        "ffprobe", (ValidationCheck("decode", observed=False, expected=True, detail="truncated"),),
        observed_checksum=CHECKSUM,
    )
    with pytest.raises(ValueError, match="PRODUCTION_RECEIPT_WITH_FAILED_VALIDATION"):
        ProductionReceipt(
            receipt_id="rc1", run_id="run1", artifact_id="art1",
            artifact_checksum=CHECKSUM, producer="p", validation_result=validation,
        )


def test_receipt_refuses_validation_of_different_bytes():
    """Validation for one file plus a checksum for another must not combine."""
    validation = ValidationResult(
        "ffprobe", (ValidationCheck("decode", observed=True, expected=True),),
        observed_checksum=checksum_bytes(b"a different artifact"),
    )
    with pytest.raises(ValueError, match="PRODUCTION_RECEIPT_VALIDATION_MISMATCH"):
        ProductionReceipt(
            receipt_id="rc1", run_id="run1", artifact_id="art1",
            artifact_checksum=CHECKSUM, producer="p", validation_result=validation,
        )


def test_receipt_requires_identity_and_producer():
    validation = _receipt().validation_result
    for field in ("receipt_id", "run_id", "producer"):
        kwargs = {
            "receipt_id": "rc1", "run_id": "run1", "artifact_id": "art1",
            "artifact_checksum": CHECKSUM, "producer": "p", "validation_result": validation,
        }
        kwargs[field] = ""
        with pytest.raises(ValueError, match="PRODUCTION_RECEIPT_WITHOUT"):
            ProductionReceipt(**kwargs)


# ══════════════════════════════════════════════════════════════════════════
# T1 — artifact_exists is not proof
# ══════════════════════════════════════════════════════════════════════════


def test_existing_artifact_with_no_bytes_yields_no_receipt():
    receipt, failure, reason = _issue(reader=lambda a: b"")
    assert receipt is None
    assert failure is ExecutionFailure.ARTIFACT_MISSING


def test_missing_artifact_yields_no_receipt():
    def missing(artifact_id: str) -> bytes:
        raise FileNotFoundError(artifact_id)

    receipt, failure, _ = _issue(reader=missing)
    assert receipt is None
    assert failure is ExecutionFailure.ARTIFACT_MISSING


def test_unreadable_artifact_is_distinguished_from_a_missing_one():
    def unreadable(artifact_id: str) -> bytes:
        raise PermissionError("denied")

    receipt, failure, _ = _issue(reader=unreadable)
    assert failure is ExecutionFailure.ARTIFACT_UNREADABLE
    assert receipt is None


def test_receipt_is_never_issued_from_a_path():
    """The receipt path takes bytes. There is no variant that takes a location."""
    tree = ast.parse(EXECUTE.read_text())
    signature_text = EXECUTE.read_text()
    assert "read_artifact" in signature_text
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "issue_receipt":
            params = {a.arg for a in node.args.args + node.args.kwonlyargs}
            assert "artifact_path" not in params and "path" not in params, (
                "issue_receipt must take bytes, not a path"
            )


# ══════════════════════════════════════════════════════════════════════════
# T4 — validation cannot be bypassed
# ══════════════════════════════════════════════════════════════════════════


def test_render_finished_plus_artifact_exists_is_not_a_receipt():
    """The exact T4 shape: completion and existence, but no validation."""
    receipt, failure, _ = _issue(validator=lambda a, p: None)
    assert receipt is None
    assert failure is ExecutionFailure.VALIDATION_NOT_RUN


def test_failed_validation_yields_no_receipt():
    receipt, failure, reason = _issue(validator=_validator(passed=False))
    assert receipt is None
    assert failure is ExecutionFailure.VALIDATION_FAILED
    assert "decode" in reason


def test_validation_of_other_bytes_yields_no_receipt():
    receipt, failure, _ = _issue(validator=_validator(payload=b"another artifact"))
    assert receipt is None
    assert failure is ExecutionFailure.PAYLOAD_MISMATCH


def test_validation_must_observe_a_digest():
    """A result that never hashed the payload says nothing about it."""
    def unhashed(artifact_id: str, body: bytes) -> ValidationResult:
        return ValidationResult("ffprobe", (ValidationCheck("decode", observed=True, expected=True),))

    assert not ValidationResult(
        "ffprobe", (ValidationCheck("decode", observed=True, expected=True),)
    ).verify_payload(BYTES)
    receipt, failure, _ = _issue(validator=unhashed)
    assert receipt is None
    assert failure is ExecutionFailure.PAYLOAD_MISMATCH


def test_validation_result_must_carry_checks():
    with pytest.raises(ValueError, match="VALIDATION_RESULT_WITHOUT_CHECKS"):
        ValidationResult("ffprobe", ())


def test_validation_cannot_claim_pass_with_a_failed_check():
    """`passed` is derived, never declared."""
    result = ValidationResult(
        "ffprobe",
        (ValidationCheck("container", observed=True, expected=True), ValidationCheck("decode", observed=False, expected=True)),
        observed_checksum=CHECKSUM,
    )
    assert result.passed is False
    assert [c.name for c in result.failed_checks] == ["decode"]


# ══════════════════════════════════════════════════════════════════════════
# T3 — execution state is not production state
# ══════════════════════════════════════════════════════════════════════════


def test_execution_state_is_disjoint_from_run_state():
    assert {s.value for s in ExecutionState}.isdisjoint({s.value for s in RunState})


def test_execution_states_are_namespaced():
    assert {s.name for s in ExecutionState} == {
        "REQUESTED", "RUNNING", "COMPLETED", "FAILED"
    }
    for state in ExecutionState:
        assert state.value.startswith("execution_"), (
            f"{state.value} could collide with RunState on the wire"
        )


def test_completed_is_not_produced():
    """Finishing an attempt is not a production verdict."""
    run = _completed()
    assert run.state is ExecutionState.COMPLETED
    assert run.state.value not in {s.value for s in RunState}
    assert "produced" not in run.state.value


def test_execution_package_never_names_run_state():
    for path in (MODELS, EXECUTE):
        assert "RunState" not in _code_identifiers(path), (
            f"{path.name} references RunState; production verdicts are P6's"
        )
        assert "ProductionRunResult" not in _code_identifiers(path)


def test_execution_package_never_sets_produced():
    for path in (MODELS, EXECUTE):
        identifiers = _code_identifiers(path)
        for token in ("PRODUCED", "QA_PASSED", "QA_FAILED", "produced"):
            assert token not in identifiers, f"{path.name} names {token}"


def test_run_state_produced_still_has_one_construction_site():
    """P7.3's I5 invariant, still holding after P8.3."""
    sites = []
    # Scoped to production/ and execution/, not the whole package. A whole-tree walk
    # makes this test hostage to unrelated files — one pre-existing module has a
    # non-raw regex that raises a SyntaxWarning, and promoting that to an error would
    # fail an execution invariant over someone else's style. These are the two trees
    # where a second construction could actually appear.
    roots = [pathlib.Path("hevi/production"), pathlib.Path("hevi/execution")]
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    for kw in node.keywords:
                        if (
                            kw.arg == "state"
                            and isinstance(kw.value, ast.Attribute)
                            and kw.value.attr == "PRODUCED"
                        ):
                            sites.append(f"{path.as_posix()}:{node.lineno}")
    assert len(sites) == 1, f"RunState.PRODUCED constructed {len(sites)}x: {sites}"


def test_incomplete_run_cannot_be_receipted():
    receipt, failure, reason = _issue(run=ExecutionRun("run9", "src1", "render@v1"))
    assert receipt is None
    assert failure is ExecutionFailure.EXECUTOR_FAILED
    assert "execution_requested" in reason


def test_source_must_match_the_run():
    """The receipt's source must be the one the run was started from."""
    receipt, failure, _ = _issue(
        source_id="a-different-source", run_source_id="src1"
    )
    assert receipt is None
    assert failure is ExecutionFailure.SOURCE_MISSING


# ══════════════════════════════════════════════════════════════════════════
# T5 — receipt uniqueness
# ══════════════════════════════════════════════════════════════════════════


def test_same_run_and_artifact_cannot_be_receipted_twice():
    ledger = ReceiptLedger()
    first, failure, _ = _issue(ledger=ledger)
    assert first is not None and failure is None
    second, failure2, reason = _issue(ledger=ledger)
    assert second is None
    assert failure2 is ExecutionFailure.ALREADY_RECEIPTED
    assert first.receipt_id in reason
    assert len(ledger) == 1


def test_different_artifacts_from_one_run_get_separate_receipts():
    ledger = ReceiptLedger()
    first, _, _ = _issue(artifact_id="art1", ledger=ledger)
    second, failure, _ = _issue(artifact_id="art2", ledger=ledger)
    assert first is not None and second is not None and failure is None
    assert len(ledger) == 2


def test_different_runs_may_receipt_the_same_artifact_id():
    ledger = ReceiptLedger()
    first, _, _ = _issue(ledger=ledger)
    second_run = ExecutionRun("run2", "src1", "render@v1").completed()
    second, failure, _ = _issue(run=second_run, artifact_id="art2", ledger=ledger)
    assert first is not None and second is not None and failure is None


def test_ledger_rejects_a_second_receipt_for_the_same_run_and_artifact():
    """The meaningful T5 case: a *different* receipt id, same run and artifact.

    Re-recording the identical object trips the id guard first, which is a weaker
    statement. Two distinct receipts for one run/artifact is the contradiction that
    matters, and it is what the identity guard exists to refuse.
    """
    ledger = ReceiptLedger()
    ledger.record(_receipt())
    twin = ProductionReceipt(
        receipt_id="rc2", run_id="run1", artifact_id="art1",
        artifact_checksum=CHECKSUM, producer="render@v1",
        validation_result=_receipt().validation_result,
    )
    with pytest.raises(ValueError, match="DUPLICATE_PRODUCTION_RECEIPT"):
        ledger.record(twin)
    assert len(ledger) == 1


def test_ledger_rejects_re_recording_the_identical_receipt():
    ledger = ReceiptLedger()
    ledger.record(_receipt())
    with pytest.raises(ValueError, match="DUPLICATE_RECEIPT_ID"):
        ledger.record(_receipt())
    assert len(ledger) == 1


def test_ledger_rejects_a_duplicate_receipt_id():
    ledger = ReceiptLedger()
    receipt = _receipt()
    ledger.record(receipt)
    other = ProductionReceipt(
        receipt_id=receipt.receipt_id, run_id="run2", artifact_id="art2",
        artifact_checksum=CHECKSUM, producer="p",
        validation_result=receipt.validation_result,
    )
    with pytest.raises(ValueError, match="DUPLICATE_RECEIPT_ID"):
        ledger.record(other)


def test_receipt_identity_is_run_and_artifact():
    assert _receipt().identity == ("run1", "art1")


# ══════════════════════════════════════════════════════════════════════════
# NO_SECOND_PRODUCTION_AUTHORITY — the P6 receipt is not duplicated
# ══════════════════════════════════════════════════════════════════════════


def test_p6_execution_receipt_still_means_a_delegate_ran():
    from hevi.production.p6.production_runtime import ExecutionReceipt as P6Receipt

    names = {f.name for f in dataclasses.fields(P6Receipt)}
    assert names == {"runtime_id", "entrypoint_ref", "produced", "detail"}
    assert "artifact_id" not in names, "P6's receipt is about delegation, not artifacts"


def test_execution_package_defines_no_execution_receipt():
    """Two types, one name, two meanings — the defect P8.2 found in its own states."""
    for path in (MODELS, EXECUTE):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                assert node.name != "ExecutionReceipt", (
                    f"{path.name} redefines ExecutionReceipt; P6 already owns that name"
                )
    identifiers = _code_identifiers(MODELS) | _code_identifiers(EXECUTE)
    assert "ExecutionReceipt" not in identifiers


def test_execution_package_does_not_import_the_p6_runtime():
    for path in (MODELS, EXECUTE):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "production" not in node.module, (
                    f"{path.name} imports {node.module}; production authority is P6's"
                )


def test_the_two_receipts_are_independent_types():
    from hevi.production.p6.production_runtime import ExecutionReceipt as P6Receipt

    assert ProductionReceipt is not P6Receipt
    assert not issubclass(ProductionReceipt, P6Receipt)
    assert not issubclass(P6Receipt, ProductionReceipt)


# ══════════════════════════════════════════════════════════════════════════
# failures stay classified
# ══════════════════════════════════════════════════════════════════════════


def test_execution_failures_are_classified():
    assert {f.value for f in ExecutionFailure} == {
        "source_missing", "executor_failed", "artifact_missing",
        "artifact_unreadable", "validation_failed", "validation_not_run",
        "payload_mismatch", "already_receipted",
    }


def test_no_bare_success_or_done_states():
    """`SUCCESS`, `DONE` and a bare `FAILED` are all collision hazards."""
    values = {s.value for s in ExecutionState}
    for banned in ("success", "done", "failed", "ok", "complete"):
        assert banned not in values, f"{banned!r} would collide with RunState"


def test_result_is_exactly_one_of_receipt_or_failure():
    """A caller must never be able to read a receipt and a failure from one result."""
    receipt, failure, reason = _issue()
    assert receipt is not None and failure is None and reason == ""
    receipt2, failure2, reason2 = _issue(validator=lambda a, p: None)
    assert receipt2 is None and failure2 is not None and reason2


def test_every_failure_carries_a_reason():
    cases = [
        _issue(reader=lambda a: b""),
        _issue(validator=lambda a, p: None),
        _issue(validator=_validator(passed=False)),
        _issue(run=ExecutionRun("r", "src1", "e")),
    ]
    for receipt, failure, reason in cases:
        assert receipt is None and failure is not None and reason


# ══════════════════════════════════════════════════════════════════════════
# checksum propagation and no renderer in this package
# ══════════════════════════════════════════════════════════════════════════


def test_checksum_propagates_from_payload_to_receipt():
    receipt, _, _ = _issue()
    assert receipt.artifact_checksum == CHECKSUM
    assert receipt.artifact_checksum == checksum_bytes(BYTES)
    assert receipt.validation_result.observed_checksum == receipt.artifact_checksum


def test_checksum_is_recomputed_not_passed_in():
    """No caller-supplied digest: it must come from the bytes."""
    tree = ast.parse(EXECUTE.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "issue_receipt":
            params = {a.arg for a in node.args.args + node.args.kwonlyargs}
            assert "checksum" not in params and "expected_checksum" not in params


def test_execution_package_contains_no_renderer():
    tree = ast.parse(EXECUTE.read_text())
    banned = {"subprocess", "Popen", "run", "shutil", "httpx", "requests", "os"}
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & banned), f"execute.py imports {imported & banned}"


def test_execution_package_touches_no_filesystem():
    """`read_artifact` is a seam; the module must not open paths itself."""
    identifiers = _code_identifiers(EXECUTE)
    for token in ("open", "Path", "os", "filesystem"):
        assert token not in identifiers, f"execute.py uses {token}"
