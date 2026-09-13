"""Small, provenance-labelled recipe catalog."""

from __future__ import annotations

from hevi.cinematic.shot_intelligence.models import CameraMotion, ShotRecipe

_PROVENANCE = {
    "source": "HEVI native synthesis informed by internal cinematic contracts",
    "repository": "hevi",
    "license": "MIT",
    "version": "1",
}


def default_catalog() -> tuple[ShotRecipe, ...]:
    return (
        ShotRecipe("establishing", "establishing", "wide", 1, constraints=("context_required",), tags=("wide",), provenance=_PROVENANCE),
        ShotRecipe("medium_dialogue", "coverage", "medium", 1, dialogue_compatible=True, tags=("dialogue",), provenance=_PROVENANCE),
        ShotRecipe("close_reaction", "reaction", "close", 1, duration_range_s=(1.0, 4.0), tags=("reaction",), provenance=_PROVENANCE),
        ShotRecipe("detail_motion", "detail", "close", 1, CameraMotion("push_in", "fast"), duration_range_s=(1.0, 4.0), tags=("detail", "motion"), provenance=_PROVENANCE),
        ShotRecipe("b_roll", "b_roll", "medium_wide", 1, duration_range_s=(1.0, 5.0), tags=("broll",), provenance=_PROVENANCE),
        ShotRecipe("cta", "cta", "medium", 1, text_overlay_compatible=True, tags=("text", "cta"), provenance=_PROVENANCE),
    )

