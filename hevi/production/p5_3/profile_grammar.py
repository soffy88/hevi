"""HEVI P5.3 — Profile-specific grammar: P2 profile -> recipe preferences.

Each of the four canonical P2 profiles has a distinct visual grammar. This
module maps a profile to preferred and avoided recipe families and specific
recipes, so retrieval can rank candidates by profile compatibility.

This does not override semantic match. Profile compatibility is one factor in
the ranking, weighted below semantic correctness.
"""

from __future__ import annotations

from typing import Any

from hevi.production.p5_3.schema import RecipeFamily

# Profile-specific grammar preferences
_PROFILE_PREFERENCES: dict[str, dict[str, Any]] = {
    "EMOTIONAL_BOOK_REVIEW": {
        "preferred_families": [
            RecipeFamily.EMOTIONAL.value,
            RecipeFamily.PRESENTER.value,
            RecipeFamily.EVIDENCE.value,
        ],
        "preferred_recipes": [
            "EMOTIONAL.SOLITUDE_HOLD",
            "EMOTIONAL.OBJECT_METAPHOR",
            "EMOTIONAL.ENVIRONMENTAL_MOOD",
            "EMOTIONAL.MEMORY_FRAGMENT",
            "EMOTIONAL.QUIET_ENDING",
            "PRESENTER.PRESENTER_PRIMARY",
            "EVIDENCE.QUOTE_WITH_SOURCE",
        ],
        "avoided_recipes": [
            "DATA.COUNTER",
            "DATA.NUMBER_REVEAL",
            "EXPLAINER.PROCESS_FLOW",
        ],
        "avoided_families": [RecipeFamily.DATA.value],
        "notes": (
            "Prefer emotional hold, object metaphor, environmental mood, "
            "memory fragment, book evidence, quiet ending. Avoid constant "
            "kinetic typography and aggressive transitions."
        ),
    },
    "WHITEBOARD_EXPLAINER": {
        "preferred_families": [
            RecipeFamily.EXPLAINER.value,
            RecipeFamily.COMPOSITION.value,
            RecipeFamily.EVIDENCE.value,
        ],
        "preferred_recipes": [
            "EXPLAINER.CONCEPT_BUILD",
            "EXPLAINER.LAYER_BY_LAYER",
            "EXPLAINER.CAUSE_EFFECT",
            "EXPLAINER.ANNOTATED_DIAGRAM",
            "EXPLAINER.PROCESS_FLOW",
            "COMPOSITION.NEGATIVE_SPACE_TEXT",
            "EVIDENCE.SCREEN_CAPTURE_FOCUS",
        ],
        "avoided_recipes": [
            "EMOTIONAL.SOLITUDE_HOLD",
            "CAMERA.CONTROLLED_ORBIT",
        ],
        "avoided_families": [RecipeFamily.EMOTIONAL.value],
        "notes": (
            "Prefer concept build, draw, arrow, highlight, cause-effect, "
            "step reveal. Avoid long static holds and aggressive camera moves."
        ),
    },
    "SCIENCE_EXPLAINER": {
        "preferred_families": [
            RecipeFamily.EVIDENCE.value,
            RecipeFamily.EXPLAINER.value,
            RecipeFamily.DATA.value,
            RecipeFamily.CAMERA.value,
        ],
        "preferred_recipes": [
            "EVIDENCE.DATA_HIGHLIGHT",
            "EVIDENCE.DOCUMENT_REVEAL",
            "EVIDENCE.SCREEN_CAPTURE_FOCUS",
            "EXPLAINER.MACRO_TO_MICRO",
            "EXPLAINER.COMPARE_CONTRAST",
            "DATA.BAR_GROWTH",
            "DATA.LINE_TRACE",
            "CAMERA.DETAIL_TO_CONTEXT",
        ],
        "avoided_recipes": [
            "EMOTIONAL.EMOTIONAL_DISTANCE",
            "PRESENTER.REACTION_HOLD",
        ],
        "avoided_families": [RecipeFamily.EMOTIONAL.value],
        "notes": (
            "Prefer evidence, diagram, scale comparison, process, data, "
            "macro/micro. Avoid emotional distance and reaction holds."
        ),
    },
    "HISTORICAL_NARRATIVE": {
        "preferred_families": [
            RecipeFamily.EVIDENCE.value,
            RecipeFamily.CAMERA.value,
            RecipeFamily.COMPOSITION.value,
        ],
        "preferred_recipes": [
            "EVIDENCE.MAP_TRACE",
            "EVIDENCE.TIMELINE_REVEAL",
            "EVIDENCE.DOCUMENT_REVEAL",
            "EVIDENCE.OBJECT_DETAIL",
            "CAMERA.PAN_REVEAL",
            "CAMERA.PARALLAX_DRIFT",
            "COMPOSITION.LAYERED_DEPTH",
        ],
        "avoided_recipes": [
            "DATA.COUNTER",
            "PRODUCT.CTA_RESOLUTION",
        ],
        "avoided_families": [RecipeFamily.PRODUCT.value],
        "notes": (
            "Prefer map, document, timeline, location transition, artifact "
            "detail, cause/consequence. Avoid product CTAs and data counters."
        ),
    },
}


def profile_recipe_preferences(profile_id: str) -> dict[str, Any]:
    """Return recipe preferences for a P2 profile.

    Returns a dict with preferred_families, preferred_recipes, avoided_recipes,
    avoided_families, and notes. Unknown profiles return empty preferences.
    """
    return _PROFILE_PREFERENCES.get(profile_id, {
        "preferred_families": [],
        "preferred_recipes": [],
        "avoided_recipes": [],
        "avoided_families": [],
        "notes": "Unknown profile; no specific preferences.",
    })


def is_profile_distinct(profile_id: str) -> bool:
    """Whether a profile has distinct preferences from the others."""
    prefs = _PROFILE_PREFERENCES.get(profile_id)
    if not prefs:
        return False
    return bool(prefs.get("preferred_recipes"))


__all__ = ["is_profile_distinct", "profile_recipe_preferences"]
