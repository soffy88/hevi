"""Canon-inheritance policy for fanfic, AU, and spinoff projects."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from hevi.obase.creative import (
    CanonDeviation,
    CanonInheritancePolicy,
    CreativeAuthority,
    ImportedCanonSnapshot,
    NarrativeCanon,
    ParentCanonRef,
)


@dataclass(frozen=True)
class DerivedCanon:
    parent_ref: ParentCanonRef
    snapshot: ImportedCanonSnapshot
    policy: CanonInheritancePolicy


class FanficModule:
    def import_parent(
        self,
        *,
        project_id: UUID,
        parent: NarrativeCanon,
        snapshot_hash: str,
        allow_deviation: bool,
        inherited_fact_types: tuple[str, ...],
    ) -> DerivedCanon:
        parent_ref = ParentCanonRef(
            project_id=project_id,
            parent_project_id=parent.project_id,
            parent_canon_revision=parent.revision,
            authority=CreativeAuthority.EVIDENCE,
        )
        snapshot = ImportedCanonSnapshot(
            project_id=project_id,
            parent_ref_id=parent_ref.object_id,
            snapshot_hash=snapshot_hash,
            fact_ids=parent.continuity_fact_ids,
            authority=CreativeAuthority.SNAPSHOT,
        )
        policy = CanonInheritancePolicy(
            project_id=project_id,
            parent_ref_id=parent_ref.object_id,
            inherited_fact_types=inherited_fact_types,
            allow_deviation=allow_deviation,
        )
        return DerivedCanon(parent_ref, snapshot, policy)

    def deviate(
        self,
        *,
        derived: DerivedCanon,
        subject: str,
        original: str,
        replacement: str,
        reason: str,
    ) -> CanonDeviation:
        if not derived.policy.allow_deviation:
            raise ValueError("CANON_DEVIATION_NOT_ALLOWED")
        return CanonDeviation(
            project_id=derived.snapshot.project_id,
            parent_snapshot_id=derived.snapshot.object_id,
            subject=subject,
            original=original,
            replacement=replacement,
            reason=reason,
            authority=CreativeAuthority.PROPOSAL,
        )


__all__ = ["DerivedCanon", "FanficModule"]
