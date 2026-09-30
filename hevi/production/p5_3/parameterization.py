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
#: Camera behavior keyword to P1 shot_size value.
#:
#: Every key here was consciously reviewed against the recipes that use it.
#: A locked camera does not determine shot size by itself — framing does — so
#: "locked" maps to the declared neutral default, which composition and crop
#: overrides then refine. That is visibly different from the old behavior, where
#: "locked" was not in any table and fell through to the same string silently.
#: Anything not in this table raises instead of defaulting.
_CAMERA_TO_SHOT_SIZE: dict[str, str] = {
    "extreme_closeup": "extreme_closeup",
    "closeup": "closeup",
    "detail": "closeup",
    "centered": "medium",
    "wide": "wide",
    "full_frame": "wide",
    "pip": "medium",
    "locked": "medium",
    "slow_push_in": "medium",
    "slow_pull_out": "medium",
    "push_in": "medium",
    "pull_out": "medium",
    "pan": "medium",
    "orbit": "medium",
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

#: Structured camera path to motion family. When a recipe declares its path,
#: the path IS the motion — no keyword inference is consulted, and the free-text
#: motion_behavior string is not read at all. A dolly is translation; a zoom is
#: focal change; the two are different facts about different physical quantities.
_STRUCTURED_PATH_TO_MOTION: dict[str, str] = {
    "DOLLY": "dolly",
    "PAN": "pan",
    "TILT": "tilt",
    "TRUCK": "truck",
    "ELEVATE": "elevate",
    "ORBIT": "orbit",
    "FOLLOW": "follow",
    "STATIC_PATH": "static",
}


def _resolve_motion_type(recipe: CinematicRecipe) -> str:
    """Resolve a recipe's motion type with structured-first precedence.

    Precedence:
      1. Structured primitive (path, focal_behavior). Authoritative.
      2. Validated explicit parameter. (No motion parameter exists yet; when one
         does, it slots in here.)
      3. Legacy compatibility mapping from motion_behavior keywords. Only for
         recipes that predate the structured primitives.
      4. REJECT. Unknown values raise; they never become "static".

    A zoom changes focal behavior. A dolly changes camera translation/path.
    The resolver keeps those separate: focal ZOOM with a static path yields
    focal semantics, while a translation path yields translation semantics
    regardless of what the free-text motion_behavior string says.
    """
    from hevi.production.p5_3.schema import VALID_FOCAL_BEHAVIOR, VALID_PATHS

    if recipe.path or recipe.focal_behavior:
        if recipe.path and recipe.path not in VALID_PATHS:
            raise ValueError(f"UNKNOWN_PRIMITIVE:PATH:{recipe.path}")
        if recipe.focal_behavior and recipe.focal_behavior not in VALID_FOCAL_BEHAVIOR:
            raise ValueError(
                f"UNKNOWN_PRIMITIVE:FOCAL_BEHAVIOR:{recipe.focal_behavior}"
            )
        if recipe.path and recipe.path != "STATIC_PATH":
            # A translation path determines the motion family on its own. The
            # free-text motion_behavior is not consulted — reading it would let
            # a stale "push_in" string override a declared DOLLY.
            return _STRUCTURED_PATH_TO_MOTION[recipe.path]
        if recipe.focal_behavior == "ZOOM":
            return "zoom"
        return "static"

    # No structured primitives: legacy compatibility path. Constrained to the
    # exact vocabulary the mapping supports; anything else fails closed.
    key = _keyword(recipe.motion_behavior)
    if not key:
        raise ValueError(
            f"UNKNOWN_PRIMITIVE:MOTION_BEHAVIOR:{recipe.motion_behavior!r}"
        )
    try:
        return _MOTION_TO_TYPE[key]
    except KeyError:
        raise ValueError(f"UNKNOWN_PRIMITIVE:MOTION_BEHAVIOR:{key}") from None


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
    """Suggest ShotPlan field values.

    Shot size has no structured primitive yet, so the legacy mapping remains
    the authority — but it is now fail-closed. An unrecognized camera behavior
    raises instead of silently becoming "medium".
    """
    key = _keyword(recipe.camera_behavior)
    if not key or key not in _CAMERA_TO_SHOT_SIZE:
        raise ValueError(
            f"UNKNOWN_PRIMITIVE:CAMERA_BEHAVIOR:{recipe.camera_behavior!r}"
        )
    shot_size = _CAMERA_TO_SHOT_SIZE[key]
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
    """Suggest MotionPlan field values.

    Structured primitives resolve first; legacy keyword mapping only for
    recipes that predate them; unknown values reject. See _resolve_motion_type.
    """
    motion_type = _resolve_motion_type(recipe)

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
    """Extract the first recognizable keyword from a behavior description.

    Legacy compatibility only. This exists solely for recipes that predate the
    structured primitives (path, focal_behavior). It must never override a
    structured primitive, and it must never silently accept an unknown value:
    callers treat an empty return as rejection, not as a default.

    The vocabulary is derived from the mapping tables it feeds, so the two
    cannot drift apart without a test noticing.
    """
    lowered = (text or "").lower()
    vocabulary = set(_CAMERA_TO_SHOT_SIZE) | set(_MOTION_TO_TYPE)
    for key in sorted(vocabulary, key=len, reverse=True):
        if key in lowered:
            return key
    return ""


__all__ = ["parameterize_recipe"]
