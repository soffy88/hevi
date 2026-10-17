"""Compatibility adapters into the canonical Production Graph."""

from .canvas import (
    CanvasProjection,
    CanvasProjectionError,
    CanvasProjectionNode,
    canvas_graph_to_projection,
    canvas_semantic_patch,
)
from .cinematic import (
    cinematic_beats_to_beats,
    cinematic_scene_to_scene,
    cinematic_shots_to_shots,
    director_shot_to_shot,
)
from .script2video import novel_plan_provenance, novel_plan_to_narrative
from .studio import (
    production_plan_to_legacy_slots,
    slate_to_production_plan,
    studio_snapshot_projection,
)
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
    "CanvasProjection",
    "CanvasProjectionError",
    "CanvasProjectionNode",
    "canvas_graph_to_projection",
    "canvas_semantic_patch",
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
    "production_plan_to_legacy_slots",
    "slate_to_production_plan",
    "source_document_from_text",
    "studio_snapshot_projection",
]
