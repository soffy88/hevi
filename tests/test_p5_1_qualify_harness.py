"""HEVI P5.1 — qualification harness hardening.

Proves the three repairs made to ``scripts/p5_1_qualify.py``:

1. A gate backed by a test file is proved by EXECUTING that file, never by
   asserting PASS because the file exists.
2. An empty test selection is a FAILURE state, not a vacuous pass.
3. The mandatory P5.1 test registry is consumed, and coverage of that registry
   is itself gated.

These tests read the harness. They do not weaken any provider gate, and they
must keep passing while the provider is still BLOCKED_BY_PROVIDER.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
QUALIFY = REPO / "scripts" / "p5_1_qualify.py"


def _load_harness():
    """Import the qualification harness as a module (it is a script, not a package).

    The module is registered in ``sys.modules`` before execution: the harness
    declares dataclasses, and their ``__module__`` lookup fails otherwise.
    """
    spec = importlib.util.spec_from_file_location("p5_1_qualify_under_test", QUALIFY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ── 1. Architecture gate must be executed, not asserted ───────────────────


def test_architecture_gate_is_not_hardcoded_pass() -> None:
    """LICENSE_BOUNDARY must be produced by running its test file.

    The prior harness returned ``ok=True`` for this source with the reason
    "audited by test_p5_1_architecture", so the gate reported PASS without ever
    executing anything. The only way to produce that source's gate now is
    ``_run_tests``.
    """
    source = (QUALIFY).read_text(encoding="utf-8")
    assert "audited by test_p5_1_architecture" not in source, (
        "the hardcoded architecture-gate PASS reason has returned"
    )
    # The per-gate loop must call _run_tests unconditionally.
    assert 'if source == "tests/test_p5_1_architecture.py"' not in source, (
        "architecture gate is still special-cased instead of executed"
    )


def test_license_boundary_gate_is_declared_against_the_architecture_file() -> None:
    harness = _load_harness()
    declared = dict(harness.GATE_ORDER)
    assert declared["LICENSE_BOUNDARY"] == "tests/test_p5_1_architecture.py"


def test_architecture_file_backs_a_gate_and_is_executed() -> None:
    """The architecture test file must exist and actually run green."""
    harness = _load_harness()
    source = "tests/test_p5_1_architecture.py"
    assert (REPO / source).is_file()
    # _run_tests must return a real result for it (PASS with real evidence).
    ok, detail = harness._run_tests([source])
    assert ok is True, detail
    assert "no tests selected" not in detail.lower()


# ── 2. Empty selection is fail-closed ─────────────────────────────────────


def test_empty_selection_is_a_failure_not_a_pass() -> None:
    """``_run_tests([])`` must never report success."""
    harness = _load_harness()
    ok, detail = harness._run_tests([])
    assert ok is False, "empty selection reported success — vacuous PASS is back"
    assert "NO_TESTS_SELECTED" in detail


def test_empty_selection_failure_text_is_explicit() -> None:
    harness = _load_harness()
    _, detail = harness._run_tests([])
    assert "refusing to report PASS" in detail


def test_missing_test_file_fails_rather_than_vacating() -> None:
    """A named-but-absent test file must FAIL, not silently pass."""
    harness = _load_harness()
    ok, _ = harness._run_tests(["tests/test_p5_1_does_not_exist.py"])
    assert ok is False


# ── 3. Mandatory registry is consumed and covered ─────────────────────────


def test_mandatory_registry_lists_every_required_file() -> None:
    """All eleven mandatory P5.1 qualification test files are declared."""
    harness = _load_harness()
    required = {
        "test_p5_1_calibration.py",
        "test_p5_1_parametric_text.py",
        "test_p5_1_architecture.py",
        "test_p5_1_review.py",
        "test_p5_1_repair.py",
        "test_p5_1_evidence.py",
        "test_p5_1_presentation.py",
        "test_p5_1_pairwise.py",
        "test_p5_1_session.py",
        "test_p5_1_adversarial.py",
        "test_p5_1_editable.py",
    }
    assert required <= set(harness.MANDATORY_P5_1_TESTS)


def test_harness_own_test_is_itself_gated() -> None:
    """This file qualifies the harness, so it must be inside the gated registry."""
    harness = _load_harness()
    assert "test_p5_1_qualify_harness.py" in harness.MANDATORY_P5_1_TESTS


def test_registry_coverage_passes_on_this_checkout() -> None:
    harness = _load_harness()
    ok, detail = harness._test_registry_coverage()
    assert ok is True, detail


def test_registry_coverage_fails_when_a_mandatory_file_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Losing a mandatory file must fail coverage, not shrink the proof."""
    harness = _load_harness()
    monkeypatch.setattr(
        harness, "MANDATORY_P5_1_TESTS", (*harness.MANDATORY_P5_1_TESTS, "test_p5_1_absent.py")
    )
    ok, detail = harness._test_registry_coverage()
    assert ok is False
    assert "MISSING_TEST_FILES" in detail


def test_registry_coverage_fails_when_a_file_is_unregistered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _load_harness()
    monkeypatch.setattr(harness, "P5_1_TESTS", [])
    ok, detail = harness._test_registry_coverage()
    assert ok is False
    assert "UNREGISTERED_TESTS" in detail


def test_registry_gate_is_declared() -> None:
    harness = _load_harness()
    declared = dict(harness.GATE_ORDER)
    assert declared["P5_1_TEST_REGISTRY"] == "registry"
    assert declared["P5_1_TEST_SUITE"] == "registry"


# ── 4. Provider blocking is preserved ─────────────────────────────────────


def test_verdict_requires_every_gate_to_pass() -> None:
    """Any non-PASS gate must block qualification."""
    harness = _load_harness()
    q = harness.Qualification(gates=[harness.Gate("A", "PASS")])
    assert q.verdict() == "QUALIFIED"
    q.gates.append(harness.Gate("B", "FAIL"))
    assert q.verdict() == "NOT_QUALIFIED"
    q2 = harness.Qualification(gates=[harness.Gate("A", "PASS")], blocked=["X"])
    assert q2.verdict() == "NOT_QUALIFIED_BLOCKED_BY_PROVIDER"


@pytest.mark.parametrize("status", ["BLOCKED_BY_PROVIDER", "SKIPPED", "NOT_EVALUATED"])
def test_no_non_pass_status_can_yield_qualified(status: str) -> None:
    """BLOCKED / SKIPPED / NOT_EVALUATED are never treated as PASS."""
    harness = _load_harness()
    q = harness.Qualification(gates=[harness.Gate("A", status)])
    assert q.verdict() != "QUALIFIED"


def test_harness_declares_no_mock_provider() -> None:
    """Hardening must not have introduced a mock or fake provider path."""
    source = QUALIFY.read_text(encoding="utf-8")
    for banned in ("MockVideo", "FakeProvider", "DummyProvider", "monkeypatch.setenv"):
        assert banned not in source, f"harness references {banned}"
