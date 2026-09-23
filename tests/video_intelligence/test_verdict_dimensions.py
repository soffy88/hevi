from __future__ import annotations

from pathlib import Path

from hevi.verdict.case_dimensions import DIMENSIONS, REASON_CODES, evaluate_case_artifact


def test_case_verdict_uses_canonical_dimensions_and_observable_evidence() -> None:
    path = Path("output/manim_smoke/equation.mp4")
    if not path.is_file():
        return
    result = evaluate_case_artifact(path)
    assert tuple(result["dimensions"]) == DIMENSIONS
    assert result["passed"] is True
    assert result["evidence"]
    for dimension in result["dimensions"].values():
        assert set(dimension) >= {
            "dimension", "status", "score", "reason_codes", "evidence_refs",
            "evaluator", "evaluator_version",
        }
        assert set(dimension["reason_codes"]).issubset(REASON_CODES)
