"""HEVI research module with an explicit reference-to-canon boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from hevi.obase.creative import (
    ContinuityFact,
    CreativeAuthority,
    CreativeEvidence,
    CreativeSource,
    ProvenanceRef,
    ResearchReport,
)


class ResearchModule:
    """Store research as evidence; only explicit acceptance creates a fact."""

    def create_report(self, *, project_id: UUID, query: str) -> ResearchReport:
        return ResearchReport(project_id=project_id, query=query, retrieved_at=datetime.now(UTC))

    def add_source(
        self,
        report: ResearchReport,
        *,
        title: str,
        uri: str,
        sha256: str | None = None,
        license_ref: str | None = None,
    ) -> tuple[ResearchReport, CreativeSource]:
        source = CreativeSource(
            project_id=report.project_id,
            title=title,
            source_type="RESEARCH",
            uri=uri,
            sha256=sha256,
            license_ref=license_ref,
            authority=CreativeAuthority.EVIDENCE,
        )
        return report.model_copy(
            update={"source_ids": (*report.source_ids, source.object_id)}
        ), source

    def add_claim(
        self,
        report: ResearchReport,
        *,
        source: CreativeSource,
        claim: str,
        locator: str | None = None,
        confidence: float = 0.5,
    ) -> tuple[ResearchReport, CreativeEvidence]:
        if source.project_id != report.project_id:
            raise ValueError("research source belongs to another project")
        evidence = CreativeEvidence(
            project_id=report.project_id,
            source_id=source.object_id,
            claim=claim,
            locator=locator,
            confidence=confidence,
            authority=CreativeAuthority.EVIDENCE,
        )
        return report.model_copy(
            update={"evidence_ids": (*report.evidence_ids, evidence.object_id)}
        ), evidence

    def accept_claim(self, evidence: CreativeEvidence) -> ContinuityFact:
        """Explicit review boundary: research never auto-commits to canon."""

        return ContinuityFact(
            project_id=evidence.project_id,
            statement=evidence.claim,
            provenance=(ProvenanceRef(ref_id=str(evidence.source_id), ref_type="RESEARCH_SOURCE"),),
            authority=CreativeAuthority.CANONICAL,
        )


__all__ = ["ResearchModule"]
