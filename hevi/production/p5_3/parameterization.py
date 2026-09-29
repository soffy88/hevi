"""HEVI P5.3 — Recipe parameterization: Recipe + Parameters -> suggestions.

P5.3 produces suggestions for ShotPlan and MotionPlan fields. It does NOT create
ShotPlan or MotionPlan objects — those remain owned by P1. The suggestions are
derived from the recipe's camera_behavior, motion_behavior, composition, and the
caller's parameters.
"""

from __future__ import annotations

from typing import Any

from hevi.production.p1_types import VisualBeat
from hevi.production.p5_3.schema import CinematicRecipe, RecipeParameters

# Map recipe camera_behavior keywords to P1 shot_size values
_CAMERA_TO_SHOT_SIZE: dict[str, str] = {
    "extreme_closeup": "extreme_closeup",
    "closeup": "closeup",
    "detail": "closeup",
    "centered": "medium",
    "wide": "wide",
    "full_frame": "wide",
    "pip": "medium",
}

# Map recipe motion_behavior keywords to P1 motion_type values
_MOTION_TO_TYPE: dict[str, str] = {
    "static_hold": "static",
    "push_in": "zoom_in",
    "pull_out": "zoom_out",
    "pan_reveal": "pan",
    "pan": "pan",
    "parallax_drift": "parallax",
    "controlled_orbit": "orbit",
    "map_trace": "map_trace",
    "slow_push": "zoom_in",
    "slow_pull": "zoom_out",
}

#: Motion types the current renderer set is known to execute natively. A recipe
#: motion outside this set keeps its own identity in the suggestion — it is
#: never rewritten to a different motion — and the suggestion carries an
#: explicit capability note instead. Silent conversion is how a map trace
#: becomes a static hold with nobody noticing.
RENDERER_NATIVE_MOTIONS = frozenset({
    "static", "zoom_in", "zoom_out", "pan", "parallax", "orbit",
})


def parameterize_recipe(
    recipe: CinematicRecipe,
    params: RecipeParameters,
    beat: VisualBeat,
) -> dict[str, Any]:
    """Produce ShotPlan and MotionPlan suggestions for one beat.

    Returns a dict with "shot_plan" and "motion_plan" keys, each containing
    suggested field values. These are suggestions only — the caller decides
    whether to use them when building the canonical ShotPlan / MotionPlan.
    """
    shot = _shot_plan_suggestions(recipe, params, beat)
    motion = _motion_plan_suggestions(recipe, params, beat)
    return {"shot_plan": shot, "motion_plan": motion}


def _shot_plan_suggestions(
    recipe: CinematicRecipe, params: RecipeParameters, beat: VisualBeat
) -> dict[str, Any]:
    """Suggest ShotPlan field values."""
    shot_size = _CAMERA_TO_SHOT_SIZE.get(
        _keyword(recipe.camera_behavior), "medium"
    )
    if params.crop:
        if "detail" in params.crop or "closeup" in params.crop:
            shot_size = "extreme_closeup"
        elif "split" in params.crop:
            shot_size = "medium"
        elif "full" in params.crop:
            shot_size = "wide"

    duration = params.duration
    if duration is None:
        min_d, max_d = recipe.duration_range
        duration = (min_d + max_d) / 2.0

    start_s = beat.timeline_start_s
    end_s = start_s + duration

    camera_setup = recipe.camera_behavior or "locked"

    return {
        "shot_size": shot_size,
        "camera_setup": camera_setup,
        "start_s": round(start_s, 3),
        "end_s": round(end_s, 3),
        "duration_s": round(duration, 3),
        "suggested_by": recipe.qualified_id,
    }


def _motion_plan_suggestions(
    recipe: CinematicRecipe, params: RecipeParameters, beat: VisualBeat
) -> dict[str, Any]:
    """Suggest MotionPlan field values."""
    motion_key = _keyword(recipe.motion_behavior)
    motion_type = _MOTION_TO_TYPE.get(motion_key, "static")

    amplitude = params.motion_amplitude
    if amplitude is None:
        amplitude = 0.3

    easing = params.easing or "ease_in_out"

    motion_params: dict[str, Any] = {
        "amplitude": amplitude,
        "easing": easing,
    }
    if params.scale is not None:
        motion_params["scale"] = params.scale
    if params.position is not None:
        motion_params["position"] = list(params.position)

    suggestion: dict[str, Any] = {
        "motion_type": motion_type,
        "motion_params": motion_params,
        "semantic_justification": recipe.intent or recipe.description,
        "suggested_by": recipe.qualified_id,
    }
    if motion_type not in RENDERER_NATIVE_MOTIONS:
        # The recipe's motion is preserved verbatim above. This note states the
        # boundary explicitly so a renderer that cannot execute it can refuse
        # rather than mis-execute, and so no downstream stage mistakes the
        # suggestion for a natively supported motion.
        suggestion["capability_limitation"] = (
            f"{motion_type}: recipe motion exceeds renderer-native set; "
            "renderer must declare support or refuse"
        )
    return suggestion


def _keyword(text: str) -> str:
    """Extract the first recognizable keyword from a behavior description."""
    lowered = (text or "").lower()
    for key in (
        "extreme_closeup", "closeup", "detail", "parallax", "orbit",
        "push_in", "pull_out", "pan", "static", "centered", "wide",
        "full_frame", "pip", "map_trace", "slow_push", "slow_pull",
    ):
        if key in lowered:
            return key
    return ""


__all__ = ["parameterize_recipe"]
