from __future__ import annotations

from pathlib import Path

from hevi.verdict.case_dimensions import (
    DIMENSIONS,
    REASON_CODES,
    CaseVerdictStatus,
    VerdictDimensionStatus,
    _case_outcome,
    evaluate_case_artifact,
)


def test_case_verdict_uses_canonical_dimensions_and_observable_evidence() -> None:
    path = Path("output/manim_smoke/equation.mp4")
    if not path.is_file():
        return
    result = evaluate_case_artifact(path)
    assert tuple(result["dimensions"]) == DIMENSIONS
    assert result["evidence"]
    for dimension in result["dimensions"].values():
        assert set(dimension) >= {
            "dimension", "status", "score", "reason_codes", "evidence_refs",
            "evaluator", "evaluator_version",
        }
        assert set(dimension["reason_codes"]).issubset(REASON_CODES)


def test_case_verdict_does_not_pass_on_probe_alone() -> None:
    """A clean ffprobe measures at most one dimension; it cannot prove 15."""
    path = Path("output/manim_smoke/equation.mp4")
    if not path.is_file():
        return
    result = evaluate_case_artifact(path)
    coverage = result["observation_coverage"]
    assert coverage["not_observed"] > 0
    assert result["status"] == CaseVerdictStatus.NOT_OBSERVED.value
    assert result["passed"] is False


def test_unobserved_dimension_never_yields_pass() -> None:
    def _dim(status: str) -> dict[str, object]:
        return {"status": status}

    outcome, _ = _case_outcome({
        "a": _dim(VerdictDimensionStatus.PASS.value),
        "b": _dim(VerdictDimensionStatus.NOT_OBSERVED.value),
    })
    assert outcome is CaseVerdictStatus.NOT_OBSERVED
    assert _case_outcome({"a": _dim(VerdictDimensionStatus.PASS.value)})[0] \
        is CaseVerdictStatus.PASS

    outcome, _ = _case_outcome({
        "a": _dim(VerdictDimensionStatus.PASS.value),
        "b": _dim(VerdictDimensionStatus.FAIL.value),
    })
    assert outcome is CaseVerdictStatus.FAIL

    outcome, _ = _case_outcome({
        "a": _dim(VerdictDimensionStatus.PASS.value),
        "b": _dim(VerdictDimensionStatus.NOT_APPLICABLE.value),
    })
    assert outcome is CaseVerdictStatus.PASS
