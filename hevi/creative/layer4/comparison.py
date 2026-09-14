"""Intent-versus-artifact comparison and proposal-only feedback."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from hevi.obase.creative import (
    ArtifactProfile,
    CreativeAuthority,
    CreativeComparison,
    NarrativeIntentProfile,
    ProvenanceRef,
    RevisionFeedback,
)


class IntentArtifactComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    dimensions: tuple[CreativeComparison, ...]


@dataclass(frozen=True)
class ComparisonFinding:
    finding_id: UUID
    dimension: str
    status: str
    explanation: str


class ComparisonModule:
    def compare(
        self,
        *,
        intent: NarrativeIntentProfile,
        artifact: ArtifactProfile,
        evidence: Iterable[ProvenanceRef] = (),
    ) -> IntentArtifactComparison:
        if intent.project_id != artifact.project_id:
            raise ValueError("COMPARISON_PROJECT_MISMATCH")
        dims: list[CreativeComparison] = []
        if intent.expected_pacing is None:
            pacing_status: Literal["PASS", "WARN", "FAIL", "NOT_EVALUABLE"] = "NOT_EVALUABLE"
            pacing_observed = "not specified"
        else:
            pacing_status = "PASS" if intent.expected_pacing in artifact.observed_text else "WARN"
            pacing_observed = ", ".join(artifact.observed_text) or "not observed"
        dims.append(
            CreativeComparison(
                project_id=intent.project_id,
                dimension="PACING",
                expected=intent.expected_pacing or "not specified",
                observed=pacing_observed,
                status=pacing_status,
                evidence=tuple(evidence),
                authority=CreativeAuthority.PROJECTION,
            )
        )
        required = set(intent.required_entities)
        observed = set(artifact.observed_entities)
        entity_status: Literal["PASS", "WARN", "FAIL", "NOT_EVALUABLE"] = (
            "NOT_EVALUABLE" if not required else "PASS" if required <= observed else "FAIL"
        )
        dims.append(
            CreativeComparison(
                project_id=intent.project_id,
                dimension="REQUIRED_ENTITY",
                expected=str(len(required)),
                observed=str(len(observed & required)),
                status=entity_status,
                evidence=tuple(evidence),
                authority=CreativeAuthority.PROJECTION,
            )
        )
        statuses = {dimension.status for dimension in dims}
        status = (
            "FAIL"
            if "FAIL" in statuses
            else "WARN"
            if "WARN" in statuses
            else "PASS"
            if "PASS" in statuses
            else "NOT_EVALUABLE"
        )
        return IntentArtifactComparison(status=status, dimensions=tuple(dims))

    def feedback(self, comparison: IntentArtifactComparison) -> tuple[RevisionFeedback, ...]:
        return tuple(
            RevisionFeedback(
                project_id=dimension.project_id,
                finding_id=dimension.object_id,
                severity="ERROR" if dimension.status == "FAIL" else "WARN",
                layer="L3_INTENT_ALIGNMENT",
                target="SHOT_PLAN",
                suggested_action=f"review {dimension.dimension}: {dimension.expected} vs {dimension.observed}",
                evidence=dimension.evidence,
                authority=CreativeAuthority.PROPOSAL,
            )
            for dimension in comparison.dimensions
            if dimension.status in {"FAIL", "WARN"}
        )


__all__ = ["ComparisonFinding", "ComparisonModule", "IntentArtifactComparison"]
