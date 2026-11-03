"""Machine-readable canonical Studio production-line registry."""

from __future__ import annotations

from typing import Any

from hevi.studio.recipes import list_recipes

CANONICAL_LINES = (
    "character_animation", "kinetic_promo", "documentary_montage", "podcast_repurpose",
    "shorts_clip", "localization_dub", "explainer", "reference_adapt", "history_scene",
    "cinematic", "director_pipeline", "talking_head", "avatar_spokesperson",
    "comic_narration",
)


def production_catalog() -> list[dict[str, Any]]:
    recipes = {item.id: item for item in list_recipes(refresh=True)}
    missing = sorted(set(CANONICAL_LINES) - set(recipes))
    if missing:
        raise RuntimeError(f"canonical lines missing from Studio registry: {missing}")
    return [{
        "line": line, "recipe": recipes[line].id, "recipe_version": "1",
        "required_capabilities": list(recipes[line].tools), "optional_capabilities": [],
        "renderer": recipes[line].render_runtime,
        "input_contract": [slot.model_dump() for slot in recipes[line].slots],
        "output_contract": {"type": "video/mp4", "final": True},
        "quality_policy": {"ffprobe": True, "video_stream": True, "duration": True, "fps": True},
    } for line in CANONICAL_LINES]


def registry_consistency() -> dict[str, Any]:
    registered = sorted(item.id for item in list_recipes(refresh=True))
    canonical = sorted(CANONICAL_LINES)
    unknown_qualification_lines = sorted(set(canonical) - set(registered))
    return {
        "registered_lines": registered,
        "qualification_lines": canonical,
        "registered_count": len(registered),
        "qualification_count": len(canonical),
        "unknown_qualification_lines": unknown_qualification_lines,
        "unqualified_registered_lines": sorted(set(registered) - set(canonical)),
        # ``passed`` only requires every canonical (qualification) line to be
        # registered. Lines registered outside the canonical set (currently
        # handdraw and scene3d) are tolerated: they stay listed in
        # ``unqualified_registered_lines`` but do not fail consistency. A
        # canonical line missing from the registry still fails it.
        "passed": not unknown_qualification_lines,
    }
