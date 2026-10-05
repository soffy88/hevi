"""Gate A/C architecture guards for the OpenShorts capability integration.

The value of these tests is that violating the spec turns them red instead of
relying on someone remembering. Each test names the spec section it enforces.

Governing decisions (P2, 2026-10-05):
  * ``ExecutorRegistry`` and ``HyperFrame`` are *abstract names* in the spec, not
    existing HEVI types. They are mapped onto the seams that already exist and
    no new authority is built (§23 non-goals: "create a second provider
    registry", "create a second verification authority").
  * Fail-closed is mechanical: an unevaluated check can never report a pass
    (§7/§8: "Unknown MUST NOT become PASS").
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import hevi.studio.ops as ops
from hevi.verdict.case_dimensions import CaseVerdictStatus, _case_outcome

REPO = Path(__file__).resolve().parents[1]
STUDIO_OPS = Path(ops.__file__)

# Spec §22 Gate A: the spec's own registry/verdict names must not be created
# verbatim as a *second* authority alongside the existing seams.
FORBIDDEN_NEW_AUTHORITY = ("ExecutorRegistry", "ExecutorQualification")

# Spec §13: no new RunState vocabulary.
FORBIDDEN_STATE_CLASSES = ("NewRunState", "JobState", "ExecutionStateV2", "PipelineRunState")


def _top_level(tree: ast.Module, kind: type) -> list[ast.AST]:
    return [n for n in tree.body if isinstance(n, kind)]


def _functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [n for n in tree.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]


def _called_name(node: ast.expr) -> str:
    """The final name in a call target. ``ast.dump`` renders ``_ok()`` as
    ``Name(id='_ok', ctx=Load())`` — with no parenthesis — so text matching on
    ``"_ok("`` silently never fires."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ast.dump(node)


class TestGateASingleAuthority:
    def test_no_executor_registry_second_authority(self) -> None:
        """§10/§22-A: no second provider registry may be introduced."""
        offenders: dict[str, list[str]] = {}
        for path in sorted((REPO / "hevi").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = {n.name for n in _top_level(tree, ast.ClassDef)}
            hits = names & set(FORBIDDEN_NEW_AUTHORITY)
            if hits:
                offenders[str(path.relative_to(REPO))] = sorted(hits)
        assert offenders == {}

    def test_no_new_run_state_vocabulary(self) -> None:
        """§13: forbidding a 4th state vocabulary."""
        offenders: dict[str, list[str]] = {}
        for path in sorted((REPO / "hevi").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = {n.name for n in _top_level(tree, ast.ClassDef)}
            hits = names & set(FORBIDDEN_STATE_CLASSES)
            if hits:
                offenders[str(path.relative_to(REPO))] = sorted(hits)
        assert offenders == {}

    def test_studio_qc_tools_cannot_return_unconditional_pass(self) -> None:
        """§8: a gate that never observed anything must not return a pass.

        Detected structurally. A textual search is not sufficient because
        ``ast.dump`` renders ``_ok(ok=True)`` as ``Call(...Constant(value=True))``
        and ``True`` as a node, not as the substring ``"ok=True"``.
        """
        unconditional: dict[str, str] = {}
        tree = ast.parse(STUDIO_OPS.read_text(encoding="utf-8"))
        for fn in _functions(tree):
            if not fn.name.startswith("qc_"):
                continue
            calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
            called = {_called_name(c.func) for c in calls}
            # Anything that could be a real observation exempts the function.
            if any("evaluate_" in name or "probe" in name for name in called):
                continue
            for call in calls:
                if _called_name(call.func) != "_ok":
                    continue
                literal_pass = [
                    kw for kw in call.keywords
                    if kw.arg == "ok"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is True
                ]
                # `_ok(ok=True)` and a bare `_ok()` both assert success.
                if literal_pass or not any(kw.arg for kw in call.keywords):
                    unconditional[fn.name] = ast.unparse(call)
        assert unconditional == {}

    def test_qc_ops_route_through_an_evaluator_or_report_blocked(self) -> None:
        """Each qc_* op must either evaluate or say it did not."""
        tree = ast.parse(STUDIO_OPS.read_text(encoding="utf-8"))
        offenders: list[str] = []
        for fn in _functions(tree):
            if not fn.name.startswith("qc_"):
                continue
            body = ast.dump(fn)
            if "_blocked" in body or "evaluate_" in body or "probe" in body:
                continue
            offenders.append(fn.name)
        assert offenders == []

    def test_blocked_helper_cannot_carry_a_pass(self) -> None:
        """`_blocked` means insufficient evidence; it must stay pass-less."""
        source = STUDIO_OPS.read_text(encoding="utf-8")
        assert 'return {"status": "blocked", "reason": reason, "passed": None, **kw}' in source


class TestGateCVerificationFailClosed:
    def test_case_verdict_is_not_pass_when_unobserved(self) -> None:
        """§7: artifact_exists != success, and unknown != PASS."""
        outcome, counts = _case_outcome(
            {"a": {"status": "PASS"}, "b": {"status": "NOT_OBSERVED"}}
        )
        assert outcome is CaseVerdictStatus.NOT_OBSERVED
        assert counts["not_observed"] == 1

    def test_real_artifact_does_not_verify_as_pass_on_probe_alone(self) -> None:
        """The 2026-09-24 real MP4 probes cleanly; it must still not be PASS."""
        artifact = REPO / "output/real_content_chain/20260924T085929Z/final_timeline.mp4"
        if not artifact.is_file():
            pytest.skip("real content artifact not present")
        from hevi.verdict.case_dimensions import evaluate_case_artifact

        verdict = evaluate_case_artifact(artifact)
        assert verdict["status"] == CaseVerdictStatus.NOT_OBSERVED.value
        assert verdict["passed"] is False

    def test_production_verdict_authority_still_fail_closed(self) -> None:
        """The aggregator's own contract must not regress while we patch around it."""
        from hevi.creative.autonomous.verdict import (
            ProductionVerdictAuthority,
            VerdictInput,
            VerdictOutcome,
        )
        from hevi.validation.artifact import (
            CheckOperator,
            ValidationCheck,
            ValidationResult,
        )

        authority = ProductionVerdictAuthority()
        assert authority.evaluate(inputs=(), artifact_validation=None).outcome \
            is VerdictOutcome.BLOCKED
        assert authority.evaluate(
            inputs=(VerdictInput(source="gate", passed=True),),
            artifact_validation=None,
        ).outcome is VerdictOutcome.BLOCKED

        passing = ValidationResult(
            validator="test",
            checks=(ValidationCheck(
                name="exists", operator=CheckOperator.NON_EMPTY, observed="bytes",
            ),),
        )
        assert authority.evaluate(
            inputs=(VerdictInput(source="gate", passed=True),),
            artifact_validation=passing,
        ).outcome is VerdictOutcome.PASS
        # One failing input is enough to flip the aggregate.
        assert authority.evaluate(
            inputs=(
                VerdictInput(source="gate", passed=True),
                VerdictInput(source="qc", passed=False),
            ),
            artifact_validation=passing,
        ).outcome is VerdictOutcome.FAIL

    def test_validation_result_rejects_zero_checks(self) -> None:
        """An artifact that was never checked has not been validated."""
        from hevi.validation.artifact import ValidationResult

        with pytest.raises(ValueError, match="VALIDATION_RESULT_WITHOUT_CHECKS"):
            ValidationResult(validator="test")