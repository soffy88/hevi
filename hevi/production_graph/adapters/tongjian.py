"""Tongjian ``ChapterIR`` → canonical narrative/character records."""

from __future__ import annotations

import hashlib
from typing import Any

from hevi.production_graph.domain import (
    Character,
    NarrativeEdge,
    NarrativeEdgeType,
    NarrativeEvent,
    NarrativeGraph,
    SourceChunk,
    SourceDocument,
    SourceKind,
    SourceReference,
)
from hevi.production_graph.ids import stable_id
from hevi.tongjian.schemas import ChapterIR


def source_document_from_text(
    *, project_id: str, revision_id: str, title: str, text: str
) -> tuple[SourceDocument, SourceChunk]:
    """Create a source document and one exact source chunk for imported text."""

    document_id = stable_id("source-document", f"{project_id}:{title}")
    chunk_id = stable_id("source-chunk", f"{document_id}:0:{len(text)}")
    document = SourceDocument(
        id=document_id,
        project_id=project_id,
        revision_id=revision_id,
        kind=SourceKind.HISTORICAL,
        title=title,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        provenance={"adapter": "tongjian", "source_title": title},
    )
    chunk = SourceChunk(
        id=chunk_id,
        revision_id=revision_id,
        document_id=document_id,
        start_offset=0,
        end_offset=len(text),
        text_hash=hashlib.sha256(text.encode()).hexdigest(),
        text=text,
    )
    return document, chunk


def chapter_characters(
    chapter: ChapterIR, *, project_id: str, revision_id: str
) -> list[Character]:
    """Project chapter character IR into stable project-level identities."""

    return [
        Character(
            id=stable_id("character", f"{project_id}:tongjian:{entry.character_id}"),
            project_id=project_id,
            revision_id=revision_id,
            canonical_name=entry.canonical_name,
            aliases=entry.aliases,
            immutable_traits={
                "faction": entry.faction,
                "fate": entry.fate,
                "source_spans": entry.source_spans,
            },
            role=entry.role_in_chapter or "supporting",
            legacy_ids={"tongjian.character_id": entry.character_id},
        )
        for entry in chapter.characters
    ]


def chapter_to_narrative(
    chapter: ChapterIR,
    *,
    project_id: str,
    revision_id: str,
    source_document_id: str,
) -> NarrativeGraph:
    """Adapt a ``ChapterIR`` without losing event source provenance."""

    event_ids = {
        event.event_id: stable_id("narrative-event", f"{project_id}:tongjian:{event.event_id}")
        for event in chapter.events
    }
    character_ids = {
        character.character_id: stable_id(
            "character", f"{project_id}:tongjian:{character.character_id}"
        )
        for character in chapter.characters
    }
    location_ids = {
        location.name: stable_id("location", f"{project_id}:tongjian:{location.name}")
        for location in chapter.locations
    }

    events: list[NarrativeEvent] = []
    for event in chapter.events:
        start, end = event.source_span
        events.append(
            NarrativeEvent(
                id=event_ids[event.event_id],
                project_id=project_id,
                revision_id=revision_id,
                source_refs=[
                    SourceReference(
                        document_id=source_document_id,
                        start_offset=max(0, start),
                        end_offset=max(start, end),
                    )
                ],
                summary=event.summary,
                temporal_order=len(events),
                character_ids=[character_ids[cid] for cid in event.actors if cid in character_ids],
                location_id=location_ids.get(event.location),
                causes=[event_ids[item] for item in event.causes if item in event_ids],
                effects=[event_ids[item] for item in event.effects if item in event_ids],
                dramatic_weight=event.dramatic_weight,
                legacy_ids={"tongjian.event_id": event.event_id},
            )
        )

    edges: list[NarrativeEdge] = []
    seen: set[tuple[str, str, NarrativeEdgeType]] = set()
    for event in chapter.events:
        for target_id, edge_type in (
            *((cause, NarrativeEdgeType.CAUSES) for cause in event.causes),
            *((effect, NarrativeEdgeType.ENABLES) for effect in event.effects),
        ):
            if target_id not in event_ids:
                continue
            source, target = (
                (event_ids[target_id], event_ids[event.event_id])
                if edge_type is NarrativeEdgeType.CAUSES
                else (event_ids[event.event_id], event_ids[target_id])
            )
            key = (source, target, edge_type)
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                NarrativeEdge(
                    id=stable_id("narrative-edge", f"{source}:{edge_type}:{target}"),
                    project_id=project_id,
                    revision_id=revision_id,
                    source_event_id=source,
                    target_event_id=target,
                    type=edge_type,
                    source_refs=[
                        SourceReference(
                            document_id=source_document_id,
                            start_offset=max(0, event.source_span[0]),
                            end_offset=max(event.source_span[0], event.source_span[1]),
                        )
                    ],
                )
            )
    graph = NarrativeGraph(
        project_id=project_id,
        revision_id=revision_id,
        events=events,
        edges=edges,
    )
    graph.validate_integrity()
    return graph


def legacy_provenance(*, chapter: ChapterIR, source_document_id: str) -> dict[str, Any]:
    """Return an explicit adapter record for debugging and final provenance."""

    return {
        "adapter": "tongjian",
        "source_document_id": source_document_id,
        "event_ids": [event.event_id for event in chapter.events],
        "character_ids": [entry.character_id for entry in chapter.characters],
    }


__all__ = [
    "chapter_characters",
    "chapter_to_narrative",
    "legacy_provenance",
    "source_document_from_text",
]
