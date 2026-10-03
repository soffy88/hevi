"""P10d verdict aggregation (§1.2 five rules). Pure, deterministic, no LLM."""

from __future__ import annotations

from hevi.creative.direction_verify.models import CheckResult


def aggregate(checks: list[CheckResult], *, hard_requirement_failed: bool = False,
              artifact_invalid: bool = False) -> str:
    """Return PASS | PASS_WITH_WARNINGS | REVISE | FAIL | INCONCLUSIVE."""
    must = [c for c in checks if c.severity == "must"]
    if any(c.result == "FAIL" for c in must):
        if hard_requirement_failed or artifact_invalid:
            return "FAIL"
        return "REVISE"
    if any(c.result in ("INCONCLUSIVE", "NOT_EVALUABLE") for c in must):
        return "INCONCLUSIVE"
    rest = [c for c in checks if c.severity in ("should", "may")]
    if any(c.result in ("FAIL", "WARN") for c in rest):
        return "PASS_WITH_WARNINGS"
    return "PASS"
