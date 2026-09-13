"""Relationship graph projection and point-in-time lookup."""

from __future__ import annotations

from datetime import datetime

from hevi.narrative.models import CharacterRelationship, StoryBible


def relationship_at(bible: StoryBible, relation_id: str, scene_time: str) -> CharacterRelationship:
    when = datetime.fromisoformat(scene_time)
    for relation in bible.relationships:
        if relation.id != relation_id:
            continue
        start = datetime.fromisoformat(relation.valid_from) if relation.valid_from else None
        end = datetime.fromisoformat(relation.valid_to) if relation.valid_to else None
        if (start is None or when >= start) and (end is None or when <= end):
            return relation
    raise KeyError(f"relationship {relation_id} is not valid at {scene_time}")
