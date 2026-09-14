"""Bounded, proposal-first narrative revision workflow."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from hevi.obase.creative import (
    CandidateRevision,
    CreativeAuthority,
    NarrativeAudit,
    RevisionProposal,
)


class RevisionLimitError(RuntimeError):
    """Raised when a bounded revision loop has no remaining pass."""


@dataclass(frozen=True)
class RevisionPolicy:
    max_passes: int = 2

    def __post_init__(self) -> None:
        if self.max_passes < 1:
            raise ValueError("max_passes must be positive")


class RevisionEngine:
    """Create proposals and candidate records without mutating canon."""

    def __init__(self, policy: RevisionPolicy | None = None) -> None:
        self.policy = policy or RevisionPolicy()

    def propose(
        self,
        *,
        project_id: UUID,
        asset_id: UUID,
        base_revision: int,
        audit: NarrativeAudit,
        change_type: str = "QUALITY_DRIVEN",
    ) -> RevisionProposal:
        if audit.status == "PASS":
            raise ValueError("cannot create a revision proposal for a passing audit")
        if not audit.findings:
            raise ValueError("failed audit must contain findings")
        reasons = tuple(
            f"{finding.dimension}: {finding.recommendation}" for finding in audit.findings
        )
        return RevisionProposal(
            project_id=project_id,
            asset_id=asset_id,
            base_revision=base_revision,
            change_type=change_type,  # type: ignore[arg-type]
            reason="; ".join(reasons),
            operations=reasons,
            authority=CreativeAuthority.PROPOSAL,
        )

    def candidate(
        self,
        *,
        project_id: UUID,
        asset_id: UUID,
        base_revision: int,
        pass_number: int,
        artifact_id: UUID | None = None,
        audit_id: UUID | None = None,
    ) -> CandidateRevision:
        if pass_number < 1 or pass_number > self.policy.max_passes:
            raise RevisionLimitError("REVISION_LIMIT")
        return CandidateRevision(
            project_id=project_id,
            asset_id=asset_id,
            base_revision=base_revision,
            candidate_revision=base_revision + pass_number,
            artifact_id=artifact_id,
            audit_id=audit_id,
            authority=CreativeAuthority.PROPOSAL,
        )


__all__ = ["RevisionEngine", "RevisionLimitError", "RevisionPolicy"]
