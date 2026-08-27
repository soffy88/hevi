"""Shared evaluation evidence models to break circular imports.

P0-B: Artifact-level Constraint Evaluation
- EvaluationEvidence: artifact + evaluator + metric + score + threshold + passed
- ConstraintEvaluation: per-constraint verdict + evidence_ids + reason
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class EvaluationEvidence(BaseModel):
    """Raw evidence from a single evaluator run against a single constraint.

    The three-state principle applies here: if evaluator cannot determine
    pass/fail (missing reference, unavailable model), it must return UNKNOWN
    rather than defaulting to PASS.
    """
    id: str
    attempt_id: str
    artifact_id: str
    constraint_id: str | None
    evaluator_id: str
    evaluator_version: str
    metric: str
    score: float | None = None
    threshold: float | None = None
    passed: bool | None = None  # None = UNKNOWN (must not default to True)
    evidence_artifact_ids: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)

    def weighted_residual(self) -> float:
        """Calculate residual severity for this evidence item.

        Returns 0 if passed, otherwise returns (score or 0.5) as severity.
        """
        return 0.0 if self.passed else (self.score or 0.5)


class ConstraintEvaluation(BaseModel):
    """Per-constraint verdict from the evaluation pipeline.

    status: pass / fail / unknown / not_applicable
    Evidence references are immutable audit trail.
    reason explains why UNKNOWN when evaluator cannot run.
    """
    constraint_id: str
    status: Literal["pass", "fail", "unknown", "not_applicable"]
    score: float | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    reason: str = ""  # why UNKNOWN; empty when pass/fail


__all__ = [
    "ConstraintEvaluation",
    "EvaluationEvidence",
]