"""Deterministic narrative audit composition.

The engine produces findings from supplied evidence. It never converts a
missing input into a passing result and it only returns recommendations; a
separate revision/approval operation is required to change canonical state.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Literal
from uuid import UUID

from hevi.creative.omodul.audit_dimensions import (
    AuditContext,
    canonical_ref,
    run_dimensions,
)
from hevi.obase.creative import (
    AuditFinding,
    CreativeArtifact,
    CreativeAuthority,
    NarrativeAudit,
    NarrativeCanon,
    ProvenanceRef,
    SceneIntent,
)


class AuditDimension(StrEnum):
    CHARACTER_CONTINUITY = "CHARACTER_CONTINUITY"
    CHARACTER_VOICE = "CHARACTER_VOICE"
    WORLD_CONTINUITY = "WORLD_CONTINUITY"
    TIMELINE_CONTINUITY = "TIMELINE_CONTINUITY"
    LOCATION_CONTINUITY = "LOCATION_CONTINUITY"
    OBJECT_CONTINUITY = "OBJECT_CONTINUITY"
    RESOURCE_CONTINUITY = "RESOURCE_CONTINUITY"
    RELATIONSHIP_CONTINUITY = "RELATIONSHIP_CONTINUITY"
    INFORMATION_CONTINUITY = "INFORMATION_CONTINUITY"
    EMOTIONAL_CONTINUITY = "EMOTIONAL_CONTINUITY"
    PHYSICAL_STATE_CONTINUITY = "PHYSICAL_STATE_CONTINUITY"
    MOTIVATION_CONTINUITY = "MOTIVATION_CONTINUITY"
    FACT_CONSISTENCY = "FACT_CONSISTENCY"
    HOOK_CONTINUITY = "HOOK_CONTINUITY"
    FORESHADOWING = "FORESHADOWING"
    PAYOFF = "PAYOFF"
    ARC_ALIGNMENT = "ARC_ALIGNMENT"
    SCENE_PURPOSE = "SCENE_PURPOSE"
    PACING = "PACING"
    REPETITION = "REPETITION"
    DIALOGUE_QUALITY = "DIALOGUE_QUALITY"
    PROSE_CLARITY = "PROSE_CLARITY"
    STYLE_ALIGNMENT = "STYLE_ALIGNMENT"
    GENRE_ALIGNMENT = "GENRE_ALIGNMENT"
    FATIGUE_WORDS = "FATIGUE_WORDS"
    LENGTH_GOVERNANCE = "LENGTH_GOVERNANCE"
    STRUCTURE = "STRUCTURE"
    POINT_OF_VIEW = "POINT_OF_VIEW"
    TONE = "TONE"
    VISUAL_FILMABILITY = "VISUAL_FILMABILITY"
    SHOT_FEASIBILITY = "SHOT_FEASIBILITY"
    SAFETY = "SAFETY"
    AUTHOR_INTENT_ALIGNMENT = "AUTHOR_INTENT_ALIGNMENT"


ALL_AUDIT_DIMENSIONS: tuple[str, ...] = tuple(item.value for item in AuditDimension)


class NarrativeAuditEngine:
    """Run fail-closed deterministic checks over available creative evidence."""

    def audit(
        self,
        *,
        project_id: UUID,
        artifact: CreativeArtifact,
        canon: NarrativeCanon,
        scene_intents: Iterable[SceneIntent] = (),
        evidence_refs: Iterable[ProvenanceRef] = (),
        text: str | None = None,
    ) -> NarrativeAudit:
        findings: list[AuditFinding] = []
        refs = tuple(evidence_refs)
        if artifact.project_id != project_id or canon.project_id != project_id:
            findings.append(
                self._finding(
                    "SAFETY",
                    "FATAL",
                    "project scope does not match audit target",
                    "stop and bind all records to one project",
                )
            )
        if artifact.authority is CreativeAuthority.CANONICAL and not artifact.provenance:
            findings.append(
                self._finding(
                    "FACT_CONSISTENCY",
                    "FATAL",
                    "canonical artifact has no provenance",
                    "attach source or production provenance before commit",
                )
            )
        scenes = tuple(scene_intents)
        if any(scene.project_id != project_id for scene in scenes):
            findings.append(
                self._finding(
                    "SCENE_PURPOSE",
                    "FATAL",
                    "scene intent belongs to another project",
                    "rebuild the scene projection in this project",
                )
            )
        if any(not scene.purpose.strip() or not scene.objective.strip() for scene in scenes):
            findings.append(
                self._finding(
                    "SCENE_PURPOSE",
                    "ERROR",
                    "one or more scenes lack purpose or objective",
                    "define the intended change before drafting",
                )
            )
        if text is not None and not text.strip():
            findings.append(
                self._finding(
                    "PROSE_CLARITY",
                    "ERROR",
                    "draft text is empty",
                    "produce a non-empty candidate before review",
                )
            )
        if not refs and not artifact.provenance:
            findings.append(
                self._finding(
                    "FACT_CONSISTENCY",
                    "ERROR",
                    "no evidence reference is available",
                    "attach evidence or mark the assertion as dramatization",
                )
            )
        status: Literal["PASS", "WARN", "FAIL"] = (
            "FAIL"
            if any(item.severity in {"ERROR", "FATAL"} for item in findings)
            else "WARN"
            if findings
            else "PASS"
        )
        return NarrativeAudit(
            project_id=project_id,
            artifact_id=artifact.object_id,
            status=status,
            findings=tuple(findings),
            dimensions_checked=ALL_AUDIT_DIMENSIONS,
            authority=CreativeAuthority.PROJECTION,
        )

    def audit_context(
        self,
        context: AuditContext,
        *,
        evidence_refs: Iterable[ProvenanceRef] = (),
    ) -> NarrativeAudit:
        """Run all 33 deterministic dimension verifiers over structured evidence.

        The envelope is fail-closed: an empty draft or an unsupported dimension
        is a finding, never a pass.  Findings carry their stable defect code,
        evidence location, and the canonical refs they contradict.
        """

        refs = tuple(evidence_refs)
        findings = tuple(
            AuditFinding(
                severity=item.severity,
                dimension=item.dimension,
                evidence=refs,
                artifact_location=item.location,
                canonical_refs=tuple(canonical_ref(ref) for ref in item.canon_refs),
                recommendation=item.recommendation,
                confidence=item.confidence,
                code=item.code,
                message=item.message,
            )
            for item in run_dimensions(context)
        )
        status: Literal["PASS", "WARN", "FAIL"] = (
            "FAIL"
            if any(item.severity in {"ERROR", "FATAL"} for item in findings)
            else "WARN"
            if findings
            else "PASS"
        )
        return NarrativeAudit(
            project_id=context.project_id,
            artifact_id=context.artifact_id,
            status=status,
            findings=findings,
            dimensions_checked=ALL_AUDIT_DIMENSIONS,
            authority=CreativeAuthority.PROJECTION,
        )

    @staticmethod
    def _finding(
        dimension: str,
        severity: str,
        evidence: str,
        recommendation: str,
    ) -> AuditFinding:
        return AuditFinding(
            severity=severity,  # type: ignore[arg-type]
            dimension=dimension,
            evidence=(),
            recommendation=recommendation,
            confidence=1.0,
            artifact_location=evidence,
        )


__all__ = ["ALL_AUDIT_DIMENSIONS", "AuditDimension", "NarrativeAuditEngine"]
