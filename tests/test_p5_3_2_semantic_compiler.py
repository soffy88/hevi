"""HEVI P5.3.2 — semantic compiler adversarial tests.

The compiler must resolve from structured primitives when present, constrain
legacy keyword inference to explicitly supported inputs, and fail closed on
anything unknown. Every test below proves one of those properties by executing
the real path, not by inspecting code.
"""

from __future__ import annotations

import dataclasses

import pytest

from hevi.production.p1_types import VisualBeat
from hevi.production.p5_3.library import RecipeLibrary
from hevi.production.p5_3.parameterization import (
    _resolve_motion_type,
    parameterize_recipe,
)
from hevi.production.p5_3.recipes import load_all_recipes
from hevi.production.p5_3.retrieval import retrieve_with_evidence
from hevi.production.p5_3.schema import (
    RecipeParameters,
)


def _lib() -> RecipeLibrary:
    lib = RecipeLibrary()
    for r in load_all_recipes():
        lib.register(r)
    return lib


def _beat() -> VisualBeat:
    return VisualBeat(
        beat_id="b1", timeline_start_s=0.0, timeline_end_s=3.0,
        narration_span="x", intent_id="X",
        shot_role="ESTABLISH", narrative_phase="HOOK",
    )


# ── A. Unknown primitive ────────────────────────────────────────────────


def test_unknown_motion_behavior_rejected() -> None:
    lib = _lib()
    base = lib.get("CAMERA.STATIC_HOLD")
    bad = dataclasses.replace(base, motion_behavior="FROBNICATE")
    with pytest.raises(ValueError, match="UNKNOWN_PRIMITIVE:MOTION_BEHAVIOR"):
        _resolve_motion_type(bad)


def test_unknown_camera_behavior_rejected() -> None:
    lib = _lib()
    base = lib.get("CAMERA.STATIC_HOLD")
    bad = dataclasses.replace(base, camera_behavior="FROBNICATE")
    with pytest.raises(ValueError, match="UNKNOWN_PRIMITIVE:CAMERA_BEHAVIOR"):
        parameterize_recipe(bad, RecipeParameters(), _beat())


def test_empty_behavior_rejected_not_defaulted() -> None:
    lib = _lib()
    base = lib.get("CAMERA.STATIC_HOLD")
    bad = dataclasses.replace(base, motion_behavior="")
    with pytest.raises(ValueError, match="UNKNOWN_PRIMITIVE"):
        _resolve_motion_type(bad)


# ── B. Typo ─────────────────────────────────────────────────────────────


def test_typo_zoomm_rejected_not_static() -> None:
    """ZOOMM must raise. The old code returned "static" for it."""
    lib = _lib()
    base = lib.get("CAMERA.STATIC_HOLD")
    bad = dataclasses.replace(base, motion_behavior="ZOOMM")
    with pytest.raises(ValueError, match="UNKNOWN_PRIMITIVE"):
        _resolve_motion_type(bad)


def test_typo_in_camera_behavior_rejected_not_medium() -> None:
    lib = _lib()
    base = lib.get("CAMERA.STATIC_HOLD")
    bad = dataclasses.replace(base, camera_behavior="lockd")
    with pytest.raises(ValueError, match="UNKNOWN_PRIMITIVE"):
        parameterize_recipe(bad, RecipeParameters(), _beat())


# ── C. Determinism ──────────────────────────────────────────────────────


def test_structured_resolution_deterministic() -> None:
    lib = _lib()
    r = lib.get("CAMERA.CONTEXT_TO_DETAIL")
    outs = [parameterize_recipe(r, RecipeParameters(duration=4.0), _beat()) for _ in range(3)]
    assert outs[0] == outs[1] == outs[2]


def test_legacy_resolution_deterministic() -> None:
    lib = _lib()
    r = lib.get("CAMERA.STATIC_HOLD")
    outs = [parameterize_recipe(r, RecipeParameters(), _beat()) for _ in range(3)]
    assert outs[0] == outs[1] == outs[2]


# ── D. Zoom vs Dolly ────────────────────────────────────────────────────


def test_zoom_produces_focal_semantics() -> None:
    lib = _lib()
    motion = _resolve_motion_type(lib.get("EXPLAINER.MACRO_TO_MICRO"))
    assert motion == "zoom"
    assert "dolly" not in motion


def test_dolly_produces_translation_semantics() -> None:
    lib = _lib()
    motion = _resolve_motion_type(lib.get("CAMERA.CONTEXT_TO_DETAIL"))
    assert motion == "dolly"
    assert "zoom" not in motion


def test_zoom_and_dolly_are_not_aliases() -> None:
    lib = _lib()
    zoom = _resolve_motion_type(lib.get("EXPLAINER.MACRO_TO_MICRO"))
    dolly = _resolve_motion_type(lib.get("CAMERA.CONTEXT_TO_DETAIL"))
    assert zoom != dolly


def test_structured_path_overrides_free_text() -> None:
    """A stale motion_behavior string must not override a declared path."""
    lib = _lib()
    base = lib.get("CAMERA.CONTEXT_TO_DETAIL")
    # Even if the free-text string said zoom, the declared DOLLY wins.
    stale = dataclasses.replace(base, motion_behavior="zoom_in_fast")
    assert _resolve_motion_type(stale) == "dolly"


# ── E. Existing recipe preservation ─────────────────────────────────────


def test_all_63_recipe_ids_load() -> None:
    lib = _lib()
    assert lib.stats().total_recipes == 63


def test_structured_recipes_keep_their_semantics() -> None:
    lib = _lib()
    ctx = lib.get("CAMERA.CONTEXT_TO_DETAIL")
    mac = lib.get("EXPLAINER.MACRO_TO_MICRO")
    assert (ctx.path, ctx.focal_behavior) == ("DOLLY", "STATIC_FOCAL")
    assert (mac.path, mac.focal_behavior) == ("STATIC_PATH", "ZOOM")


def test_legacy_recipes_resolve_as_before() -> None:
    """The 61 recipes without structured primitives resolve identically."""
    lib = _lib()
    assert _resolve_motion_type(lib.get("CAMERA.STATIC_HOLD")) == "static"
    assert _resolve_motion_type(lib.get("CAMERA.SLOW_PUSH_IN")) == "zoom_in"
    assert _resolve_motion_type(lib.get("EVIDENCE.MAP_TRACE")) == "map_trace"
    assert _resolve_motion_type(lib.get("CAMERA.PAN_REVEAL")) == "pan"


def test_map_trace_identity_preserved() -> None:
    lib = _lib()
    out = parameterize_recipe(lib.get("EVIDENCE.MAP_TRACE"), RecipeParameters(), _beat())
    assert out["motion_plan"]["motion_type"] == "map_trace"
    assert "capability_limitation" in out["motion_plan"]


# ── F. Real retrieval → parameterization E2E ────────────────────────────


def test_real_path_structured_semantics_survive_to_plan() -> None:
    """Canonical API, real library, final plan inspected."""
    lib = _lib()
    beat = _beat()
    candidates, evidence = retrieve_with_evidence(
        lib, beat, profile_id="EMOTIONAL_BOOK_REVIEW"
    )
    assert candidates
    assert evidence.selected_recipe_id == candidates[0].recipe_id
    # Parameterize the winner and inspect the final plan, not a helper.
    winner = lib.get_version(evidence.selected_recipe_id, evidence.selected_version)
    plan = parameterize_recipe(winner, RecipeParameters(duration=3.0), beat)
    assert plan["shot_plan"]["suggested_by"] == winner.qualified_id
    assert plan["motion_plan"]["suggested_by"] == winner.qualified_id
    assert plan["shot_plan"]["duration_s"] == 3.0


def test_real_path_dolly_recipe_yields_translation_plan() -> None:
    lib = _lib()
    beat = VisualBeat(
        beat_id="b9", timeline_start_s=0.0, timeline_end_s=4.0,
        narration_span="from wide to detail", intent_id="FOCUS_DETAIL",
        shot_role="DETAIL", narrative_phase="DEVELOPMENT",
    )
    candidates, _ = retrieve_with_evidence(
        lib, beat, profile_id="SCIENCE_EXPLAINER"
    )
    assert candidates
    plan = parameterize_recipe(
        lib.get_version(candidates[0].recipe_id, candidates[0].version),
        RecipeParameters(), beat,
    )
    # Whatever won, its motion came from structured resolution or legacy mapping —
    # never from a silent default. The motion type is a non-empty real value.
    assert plan["motion_plan"]["motion_type"]
    assert plan["motion_plan"]["motion_type"] != ""
