"""StoryBible construction, validation and comparison."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from pydantic import TypeAdapter

from hevi.narrative.models import SCHEMA_VERSION, StoryBible, to_dict


class NarrativeSchemaError(ValueError):
    """A canonical narrative object failed schema or reference validation."""


_BIBLE_ADAPTER = TypeAdapter(StoryBible)


def create_bible(project_id: str, **changes: Any) -> StoryBible:
    return StoryBible(project_id=project_id, **changes)


def restore_bible(payload: dict[str, Any]) -> StoryBible:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise NarrativeSchemaError(f"unsupported schema_version={payload.get('schema_version')!r}")
    bible = _BIBLE_ADAPTER.validate_python(payload)
    validate_bible(bible)
    return bible


def validate_bible(bible: StoryBible) -> None:
    if not bible.project_id:
        raise NarrativeSchemaError("project_id is required")
    for label, values in {
        "characters": bible.characters,
        "relationships": bible.relationships,
        "world_rules": bible.world_rules,
        "locations": bible.locations,
        "timeline": bible.timeline,
        "facts": bible.established_facts,
        "constraints": bible.continuity_constraints,
        "episodes": bible.episodes,
        "sequences": bible.sequences,
        "threads": (*bible.unresolved_threads, *bible.resolved_threads),
    }.items():
        ids = [getattr(item, "id", getattr(item, "episode_id", None)) for item in values]
        if len(ids) != len(set(ids)):
            raise NarrativeSchemaError(f"duplicate {label} id")
    character_ids = {item.id for item in bible.characters}
    for relation in bible.relationships:
        if relation.from_character not in character_ids or relation.to_character not in character_ids:
            raise NarrativeSchemaError(f"dangling relationship {relation.id}")
    fact_ids = {item.id for item in bible.established_facts}
    for fact in bible.established_facts:
        if fact.type in {"SOURCE_FACT", "DERIVED_CLAIM"} and not fact.evidence_refs:
            raise NarrativeSchemaError(f"missing evidence for factual assertion {fact.id}")
        if fact.type == "DRAMATIZATION" and fact.historically_verified:
            raise NarrativeSchemaError(f"dramatisation cannot be historically verified: {fact.id}")
    for sequence in bible.sequences:
        if not sequence.id:
            raise NarrativeSchemaError("sequence id is required")
    for episode in bible.episodes:
        for beat in episode.beats:
            if any(ref not in fact_ids for ref in beat.source_claim_ids):
                raise NarrativeSchemaError(f"dangling claim in beat {beat.id}")


def update_bible(bible: StoryBible, **changes: Any) -> StoryBible:
    updated = replace(bible, **changes, revision=str(int(bible.revision) + 1))
    validate_bible(updated)
    return updated


def compare_bible(left: StoryBible, right: StoryBible) -> dict[str, Any]:
    before = to_dict(left)
    after = to_dict(right)
    return {"changed": before != after, "before_revision": left.revision, "after_revision": right.revision, "before": before, "after": after}
