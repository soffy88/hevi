"""Evidence-normalized quality evaluation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .gate_policy import GatePolicy
from .taxonomy import FailureCode, normalize_failure, severity_for


class QualityEvidence(BaseModel):
    code: FailureCode
    scope: str = ""
    passed: bool
    severity: float | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)

    def weighted_residual(self) -> float:
        return 0.0 if self.passed else (self.severity or severity_for(self.code))


class QualityEvaluation(BaseModel):
    passed: bool
    score: float = 1.0
    residual_severity: float = 0.0
    residual_count: int = 0
    evidence: list[QualityEvidence] = Field(default_factory=list)

    @classmethod
    def from_evidence(
        cls, evidence: list[QualityEvidence], policy: GatePolicy
    ) -> QualityEvaluation:
        residual = [item for item in evidence if not item.passed]
        blocking = [item for item in residual if policy.blocks(item.code)]
        total = sum(item.severity or severity_for(item.code) for item in evidence)
        residual_severity = sum(item.weighted_residual() for item in evidence)
        score = 1.0 if total == 0 else max(0.0, 1.0 - residual_severity / total)
        return cls(
            passed=not blocking,
            score=score,
            residual_severity=residual_severity,
            residual_count=len(residual),
            evidence=evidence,
        )


def evaluation_from_shot_verdicts(
    verdicts: list[Any], policy: GatePolicy
) -> QualityEvaluation:
    evidence: list[QualityEvidence] = []
    for verdict in verdicts:
        if getattr(verdict, "passed", True):
            continue
        code = normalize_failure(getattr(verdict, "diagnosis_category", None))
        evidence.append(
            QualityEvidence(
                code=code,
                scope=str(getattr(verdict, "shot_id", "")),
                passed=False,
                evidence=dict(getattr(verdict, "checks", {}) or {}),
            )
        )
    return QualityEvaluation.from_evidence(evidence, policy)


__all__ = ["QualityEvaluation", "QualityEvidence", "evaluation_from_shot_verdicts"]

