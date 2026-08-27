"""Profile-specific fail-open/fail-closed quality gate policy.

P0-B: GatePolicy now supports:
- verify_compilation_integrity(): preflight check (compilation/unsupported/silent drops)
- evaluate_delivery_artifacts(): artifact-level evaluation with three-state UNKNOWN
- fail-closed for Cinema/Standard required constraints
- fail-open for Economy with explicit degraded status
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .evidence import EvaluationEvidence
from .taxonomy import FailureCode, normalize_failure


class GatePolicy(BaseModel):
    profile: Literal["economy", "standard", "cinema"] = "standard"
    identity_floor: float = Field(default=0.75, ge=0.0, le=1.0)
    required_failures: set[FailureCode] = Field(default_factory=set)
    advisory_failures: set[FailureCode] = Field(default_factory=set)
    artifact_required: bool = True
    allow_checker_failure: bool = False

    @classmethod
    def for_profile(cls, profile: str = "standard") -> GatePolicy:
        profile = profile if profile in {"economy", "standard", "cinema"} else "standard"
        if profile == "economy":
            required = {
                FailureCode.DELIVERY_INTEGRITY,
                FailureCode.SAFETY_POLICY,
            }
            advisory = {
                FailureCode.IDENTITY_MISMATCH,
                FailureCode.ANATOMY_ARTIFACT,
                FailureCode.SCENE_CONTINUITY,
                FailureCode.QUALITY_CHECKER_FAILURE,
            }
            floor = 0.60
        elif profile == "cinema":
            required = set(FailureCode)
            advisory = set()
            floor = 0.85
        else:
            required = {
                FailureCode.DELIVERY_INTEGRITY,
                FailureCode.IDENTITY_MISMATCH,
                FailureCode.SCENE_CONTINUITY,
                FailureCode.EYELINE_VIOLATION,
                FailureCode.DIALOGUE_MISSING,
                FailureCode.ANATOMY_ARTIFACT,
                FailureCode.CAMERA_CONTRACT,
                FailureCode.ACTION_MISSING,
                FailureCode.SAFETY_POLICY,
                FailureCode.QUALITY_CHECKER_FAILURE,
            }
            advisory = {
                FailureCode.WARDROBE_MISMATCH,
                FailureCode.ANATOMY_ARTIFACT,
                FailureCode.STYLE_DRIFT,
            }
            floor = 0.75
        return cls(
            profile=profile,  # type: ignore[arg-type]
            identity_floor=floor,
            required_failures=required,
            advisory_failures=advisory,
        )

    def blocks(self, code: FailureCode | str) -> bool:
        return normalize_failure(code) in self.required_failures


def verify_compilation_integrity(
    compiled: int,
    required: int,
    unsupported: list[str],
    silent_drops: list[str],
    profile: str = "standard",
) -> dict[str, Any]:
    """P0-B: Preflight verifier for compilation stage.

    Checks that all required constraints are compiled and none are silently dropped.
    Returns dict with 'passed' and 'issues' list.
    """
    issues: list[str] = []
    if compiled < required:
        issues.append(f"Not all required constraints compiled: {compiled}/{required}")
    if silent_drops:
        issues.append(f"Silent drops detected: {silent_drops}")
    if unsupported:
        # Check if unsupported are all advisory
        # In a real impl, check severity; for now, any unsupported required = issue.
        issues.extend(f"Unsupported constraint: {constraint_id}" for constraint_id in unsupported)

    return {
        "passed": len(issues) == 0,
        "issues": issues,
        "coverage": compiled / required if required > 0 else 1.0,
    }


def evaluate_delivery_artifacts(
    evidence: list[EvaluationEvidence],
    policy: GatePolicy,
) -> dict[str, Any]:
    """P0-B: Artifact-level evaluation per constraint.

    Implements the three-state principle:
    - PASS: evaluator confirms constraint satisfied
    - FAIL: evaluator confirms violation
    - UNKNOWN: evaluator cannot determine (no reference, model unavailable)

    For Cinema/Standard: UNKNOWN on required constraints = BLOCKED
    For Economy: UNKNOWN may fail-open but with explicit 'degraded' status
    """
    blocking: list[str] = []
    degraded: bool = False
    unknowns: list[str] = []

    for ev in evidence:
        if ev.passed is None:
            # UNKNOWN state
            unknowns.append(ev.constraint_id or ev.evaluator_id)
            if policy.profile in ("cinema", "standard"):
                # UNKNOWN blocks for cinema/standard if it's a required constraint
                if policy.blocks(normalize_failure(ev.metric)):
                    blocking.append(f"unknown_required:{ev.evaluator_id}")
                degraded = True
            else:
                # Economy: fail-open with degraded
                degraded = True
        elif not ev.passed:
            # FAIL
            if policy.blocks(normalize_failure(ev.metric)):
                blocking.append(f"failed:{ev.evaluator_id}")
            elif ev.metric in [code.value for code in policy.advisory_failures]:
                degraded = True

    return {
        "passed": len(blocking) == 0,
        "degraded": degraded,
        "blocking": blocking,
        "unknowns": unknowns,
        "evidence_count": len(evidence),
    }


def gate_verdict(
    evidence: list[EvaluationEvidence],
    policy: GatePolicy,
    coverage: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Full GateVerdict: aggregate constraint_graph + consumption_receipts + evaluations.

    Coverage check (P0-A):
    - Cinema: required constraint provider_submission_coverage = 100%, silent_drop_rate = 0
    - Standard: required = 100% with some advisory relaxation
    - Economy: fail-open allowed with degraded flag
    """
    # Coverage check
    cov_passed = True
    cov_issues: list[str] = []
    if coverage:
        provider_submission = coverage.get("provider_submission_rate", 1.0)
        silent_drop = coverage.get("silent_drop_rate", 0.0)

        if policy.profile == "cinema":
            if provider_submission < 1.0:
                cov_passed = False
                cov_issues.append(f"provider_submission_coverage={provider_submission:.2%} < 100%")
            if silent_drop > 0:
                cov_passed = False
                cov_issues.append(f"silent_drop_rate={silent_drop:.2%} > 0%")
        elif policy.profile == "standard":
            if provider_submission < 0.95:
                cov_passed = False
                cov_issues.append(f"provider_submission_coverage={provider_submission:.2%} < 95%")
            if silent_drop > 0.01:
                cov_passed = False
                cov_issues.append(f"silent_drop_rate={silent_drop:.2%} > 1%")

    # Evaluation check
    eval_result = evaluate_delivery_artifacts(evidence, policy)

    return {
        "passed": cov_passed and eval_result["passed"],
        "degraded": eval_result["degraded"] or bool(coverage and coverage.get("verification_rate", 1.0) < 1.0),
        "coverage_passed": cov_passed,
        "coverage_issues": cov_issues,
        "evaluation": eval_result,
    }


__all__ = [
    "GatePolicy",
    "evaluate_delivery_artifacts",
    "gate_verdict",
    "verify_compilation_integrity",
]
