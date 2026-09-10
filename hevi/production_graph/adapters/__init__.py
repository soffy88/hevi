"""Compatibility adapters into the canonical Production Graph."""

from .cinematic import (
    cinematic_beats_to_beats,
    cinematic_scene_to_scene,
    cinematic_shots_to_shots,
    director_shot_to_shot,
)
from .script2video import novel_plan_provenance, novel_plan_to_narrative
from .tongjian import (
    chapter_characters,
    chapter_to_narrative,
    legacy_provenance,
    source_document_from_text,
)
from .vault import manifest_to_character, manifest_to_look_variant, manifest_to_reference_items

__all__ = [
    "chapter_characters",
    "chapter_to_narrative",
    "cinematic_beats_to_beats",
    "cinematic_scene_to_scene",
    "cinematic_shots_to_shots",
    "director_shot_to_shot",
    "legacy_provenance",
    "manifest_to_character",
    "manifest_to_look_variant",
    "manifest_to_reference_items",
    "novel_plan_provenance",
    "novel_plan_to_narrative",
    "source_document_from_text",
]
