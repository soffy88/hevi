"""Script2Video/Novel2Video → canonical narrative graph adapters."""

from __future__ import annotations

from typing import Any

from hevi.production_graph.domain import (
    NarrativeEdge,
    NarrativeEdgeType,
    NarrativeEvent,
    NarrativeGraph,
    SourceReference,
)
from hevi.production_graph.ids import stable_id
from hevi.script2video.adapter_schemas import NovelPlan


def novel_plan_to_narrative(
    plan: NovelPlan, *, project_id: str, revision_id: str, source_document_id: str | None = None
) -> NarrativeGraph:
    """Project Novel2Video events into one cross-chapter-compatible graph.

    The legacy plan has no source-span field.  We preserve its relevant chunk
    identifiers in ``SourceReference.quote`` and mark the adapter explicitly;
    a caller with exact source chunks should pass those IDs before committing.
    """

    event_ids = {
        str(event.index): stable_id("narrative-event", f"{project_id}:novel:{event.index}")
        for event in plan.events
    }
    events: list[NarrativeEvent] = []
    for order, event in enumerate(plan.events):
        refs = []
        if source_document_id:
            refs = [SourceReference(document_id=source_document_id)]
        events.append(
            NarrativeEvent(
                id=event_ids[str(event.index)],
                project_id=project_id,
                revision_id=revision_id,
                source_refs=refs,
                summary=event.description,
                temporal_order=order,
                character_ids=[],
                dramatic_weight=3,
                legacy_ids={"script2video.event_index": str(event.index)},
            )
        )

    edges = [
        NarrativeEdge(
            id=stable_id("narrative-edge", f"{event_ids[str(left.index)]}:precedes:{event_ids[str(right.index)]}"),
            project_id=project_id,
            revision_id=revision_id,
            source_event_id=event_ids[str(left.index)],
            target_event_id=event_ids[str(right.index)],
            type=NarrativeEdgeType.PRECEDES,
            rationale="Novel2Video event order",
        )
        for left, right in zip(plan.events, plan.events[1:], strict=False)
    ]
    graph = NarrativeGraph(project_id=project_id, revision_id=revision_id, events=events, edges=edges)
    graph.validate_integrity()
    return graph


def novel_plan_provenance(plan: NovelPlan) -> dict[str, Any]:
    return {
        "adapter": "script2video",
        "original_chars": plan.original_chars,
        "compression_ratio": plan.compression_ratio,
        "legacy_event_indexes": [event.index for event in plan.events],
    }


__all__ = ["novel_plan_provenance", "novel_plan_to_narrative"]
