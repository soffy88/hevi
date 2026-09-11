"""Canonical creative provenance helpers layered on the existing artifacts."""

from __future__ import annotations

from collections.abc import Iterable
from itertools import pairwise
from typing import Any

from hevi.production_graph.domain import ProvenanceLink


class ProvenanceReport:
    def __init__(
        self, *, broken_edges: int, orphan_nodes: int, unbound_final_artifacts: int
    ) -> None:
        self.broken_edges = broken_edges
        self.orphan_nodes = orphan_nodes
        self.unbound_final_artifacts = unbound_final_artifacts


def validate_creative_provenance(snapshot: Any) -> ProvenanceReport:
    """Validate persisted provenance edges against the canonical snapshot."""

    known: set[tuple[str, str]] = set()
    for field, kind in (
        ("sources", "SourceDocument"),
        ("source_chunks", "SourceChunk"),
        ("adaptation_decisions", "AdaptationDecision"),
        ("episodes", "Episode"),
        ("scenes", "Scene"),
        ("beats", "Beat"),
        ("shots", "ShotRevision"),
        ("keyframes", "Keyframe"),
        ("reference_bundles", "ReferenceBundle"),
        ("director_decisions", "DirectorDecision"),
        ("execution_plans", "ExecutionPlan"),
        ("execution_attempts", "ExecutionAttempt"),
    ):
        known.update((kind, item.id) for item in getattr(snapshot, field, []))
    known.update(
        ("NarrativeEvent", item.id)
        for item in (snapshot.narrative.events if snapshot.narrative else [])
    )
    known.update(("ShotReadinessResult", item.shot_id) for item in snapshot.readiness_results)
    artifact_ids = {
        artifact_id
        for attempt in snapshot.execution_attempts
        for artifact_id in attempt.artifact_ids
    }
    known.update(("Artifact", item) for item in artifact_ids)
    broken = sum(
        1
        for link in snapshot.provenance_links
        if (link.source_type, link.source_id) not in known
        or (link.target_type, link.target_id) not in known
    )
    referenced = {(link.source_type, link.source_id) for link in snapshot.provenance_links} | {
        (link.target_type, link.target_id) for link in snapshot.provenance_links
    }
    required = {
        "SourceDocument",
        "SourceChunk",
        "NarrativeEvent",
        "AdaptationDecision",
        "Episode",
        "Scene",
        "Beat",
        "ShotRevision",
        "Keyframe",
        "ReferenceBundle",
        "ShotReadinessResult",
        "ExecutionPlan",
        "ExecutionAttempt",
    }
    orphan = sum(
        1 for kind in required if not any(item_kind == kind for item_kind, _ in referenced)
    )
    final_bound = sum(
        1
        for attempt in snapshot.execution_attempts
        if attempt.status == "completed" and attempt.artifact_ids
    )
    return ProvenanceReport(
        broken_edges=broken, orphan_nodes=orphan, unbound_final_artifacts=0 if final_bound else 1
    )


def provenance_link(
    *,
    project_id: str,
    source_type: str,
    source_id: str,
    target_type: str,
    target_id: str,
    relation: str,
    metadata: dict[str, Any] | None = None,
) -> ProvenanceLink:
    return ProvenanceLink(
        project_id=project_id,
        source_type=source_type,
        source_id=source_id,
        target_type=target_type,
        target_id=target_id,
        relation=relation,
        metadata=dict(metadata or {}),
    )


def provenance_chain(project_id: str, nodes: Iterable[tuple[str, str]]) -> list[ProvenanceLink]:
    """Create a linear source-to-artifact chain for deterministic fixtures."""

    items = list(nodes)
    return [
        provenance_link(
            project_id=project_id,
            source_type=source_type,
            source_id=source_id,
            target_type=target_type,
            target_id=target_id,
            relation="DERIVES",
        )
        for (source_type, source_id), (target_type, target_id) in pairwise(items)
    ]


__all__ = [
    "ProvenanceReport",
    "provenance_chain",
    "provenance_link",
    "validate_creative_provenance",
]
