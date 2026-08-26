"""Evidence-normalized quality evaluation.

P0-B: Artifact-level Constraint Evaluation
- EvaluationEvidence: artifact + evaluator + metric + score + threshold + passed
- ConstraintEvaluation: per-constraint verdict + evidence_ids + reason
- Three-state principle: PASS / FAIL / UNKNOWN (no PASS when uncertain)
- GatePolicy split: verify_compilation_integrity() vs evaluate_delivery_artifacts()
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .evidence import EvaluationEvidence, ConstraintEvaluation
from .gate_policy import GatePolicy
from .taxonomy import FailureCode


class QualityEvidence(BaseModel):
    """Deprecated alias - kept for backward compatibility."""
    code: FailureCode
    scope: str = ""
    passed: bool
    severity: float | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)

    def weighted_residual(self) -> float:
        return 0.0 if self.passed else (self.severity or 0.5)


class QualityEvaluation(BaseModel):
    """Aggregate quality verdict from all constraint evaluations.

    score: weighted evaluation score (NOT consumed/total)
    passed: gate_policy.evaluate() result
    evidence: all EvaluationEvidence
    violations: ConstraintEvaluation[] for failed/unknown constraints
    """
    passed: bool
    score: float = 1.0
    residual_severity: float = 0.0
    residual_count: int = 0
    evidence: list[EvaluationEvidence] = Field(default_factory=list)
    violations: list[ConstraintEvaluation] = Field(default_factory=list)

    @classmethod
    def from_evidence(
        cls, evidence: list[EvaluationEvidence], policy: GatePolicy
    ) -> QualityEvaluation:
        """Build QualityEvaluation from raw evidence using three-state principle.

        UNKNOWN is treated as blocking for Cinema/Standard, advisory for Economy.
        Never default UNKNOWN -> PASS.
        """
        residual = [item for item in evidence if not item.passed]
        # UNKNOWN items: block only if required profile
        unknowns = [item for item in residual if item.evaluator_id and item.passed is None]
        known_pass = [item for item in evidence if item.passed is True]
        known_fail = [item for item in evidence if item.passed is False]

        blocking: list[EvaluationEvidence] = []
        advisory: list[EvaluationEvidence] = []

        for item in known_fail:
            if policy.blocks(item.evaluator_id):
                blocking.append(item)
            else:
                advisory.append(item)

        for item in known_pass:
            # PASS never blocks, but advisory floor may apply
            advisory.append(item)

        for item in unknowns:
            # Three-state: if this is a required constraint and we have UNKNOWN,
            # it blocks for Cinema/Standard; advisory for Economy
            if policy.profile == "cinema":
                blocking.append(item)
            elif policy.profile == "standard":
                # UNKNOWN blocks required constraints
                if (item.evaluator_id in policy.required_failures or
                    item.evaluator_id in {
                        FailureCode.DELIVERY_INTEGRITY.value,
                        FailureCode.IDENTITY_MISMATCH.value,
                        FailureCode.SCENE_CONTINUITY.value,
                        FailureCode.EYELINE_VIOLATION.value,
                        FailureCode.DIALOGUE_MISSING.value,
                        FailureCode.ANATOMY_ARTIFACT.value,
                        FailureCode.CAMERA_CONTRACT.value,
                        FailureCode.ACTION_MISSING.value,
                        FailureCode.SAFETY_POLICY.value,
                    }):
                    blocking.append(item)
                else:
                    advisory.append(item)
            else:  # economy
                advisory.append(item)

        # Compute score based on known results only; UNKNOWN contributes 0.5 penalty
        total_severity = sum((item.score or 0.5) for item in evidence)
        resolved_severity = sum(
            item.score or 0.5 for item in known_fail
        )
        score = 1.0 if total_severity == 0 else max(0.0, 1.0 - resolved_severity / total_severity)
        if unknowns:
            score *= 0.5  # penalty for unknowns

        violations: list[ConstraintEvaluation] = []
        for item in evidence:
            if item.passed is True:
                continue
            if item.passed is None:
                status = "unknown"
            else:
                status = "fail"
            violations.append(
                ConstraintEvaluation(
                    constraint_id=item.constraint_id or "",
                    status=status,
                    score=item.score,
                    evidence_ids=[item.id],
                    reason=item.details.get("reason", ""),
                )
            )

        return cls(
            passed=len(blocking) == 0,
            score=round(score, 4),
            residual_severity=sum(item.weighted_residual() for item in residual),
            residual_count=len(residual),
            evidence=evidence,
            violations=violations,
        )


def evaluation_from_shot_verdicts(
    verdicts: list[Any], policy: GatePolicy
) -> QualityEvaluation:
    """Build QualityEvaluation from shot verdicts.

    Deprecated: prefer the new EvaluationEvidence → QualityEvaluation.from_evidence()
    pipeline for proper three-state handling.
    """
    evidence: list[EvaluationEvidence] = []
    for verdict in verdicts:
        if getattr(verdict, "passed", True):
            continue
        code = getattr(verdict, "diagnosis_category", None)
        # NEW: unknown when we cannot determine
        if code is None:
            evidence.append(
                EvaluationEvidence(
                    id="",
                    attempt_id="",
                    artifact_id="",
                    constraint_id="",
                    evaluator_id="unknown",
                    evaluator_version="0.0.0",
                    metric="unknown",
                    passed=None,  # UNKNOWN by default
                    evidence_artifact_ids=[],
                    details={"reason": "could_not_determine_diagnosis"},
                )
            )
            continue
        evidence.append(
            EvaluationEvidence(
                id="",
                attempt_id="",
                artifact_id="",
                constraint_id="",
                evaluator_id=code,
                evaluator_version="legacy",
                metric=str(code),
                passed=False,  # known failure from verdict
                evidence_artifact_ids=[],
                details={"reason": getattr(verdict, "checks", {}) or {}},
            )
        )
    return QualityEvaluation.from_evidence(evidence, policy)


__all__ = [
    "EvaluationEvidence",
    "ConstraintEvaluation",
    "QualityEvidence",
    "QualityEvaluation",
    "evaluation_from_shot_verdicts",
]