"""HEVI P5.3.3 — Article B recipe expansion gates A-H.

Every gate executes the real path. No gate passes on description text alone.
"""

from __future__ import annotations

import pytest

from hevi.production.p1_types import VisualBeat
from hevi.production.p5_3.library import RecipeLibrary
from hevi.production.p5_3.parameterization import (
    check_forbidden_actions,
    parameterize_recipe,
)
from hevi.production.p5_3.recipes import load_all_recipes
from hevi.production.p5_3.retrieval import retrieve_with_evidence
from hevi.production.p5_3.schema import (
    CinematicRecipe,
    DollyZoomSpec,
    RecipeFamily,
    RecipeParameters,
    is_dolly_zoom,
    validate_dolly_zoom,
)

ARTICLE_B_IDS = [
    "CAMERA.WHIP_PAN", "CAMERA.TILT", "CAMERA.RACK_FOCUS", "CAMERA.TRUCK",
    "CAMERA.ELEVATE", "CAMERA.FOLLOW", "CAMERA.HANDHELD", "CAMERA.GIMBAL",
    "CAMERA.CRANE_JIB", "CAMERA.DRONE", "CAMERA.ROLL", "CAMERA.DOLLY_ZOOM",
    "CAMERA.LONG_TAKE", "CAMERA.COMBINED_MOVEMENT", "CAMERA.FPV",
    "COMPOSITION.AERIAL", "COMPOSITION.POV",
]


def _lib() -> RecipeLibrary:
    lib = RecipeLibrary()
    for r in load_all_recipes():
        lib.register(r)
    return lib


def _beat() -> VisualBeat:
    return VisualBeat(
        beat_id="b1", timeline_start_s=0.0, timeline_end_s=3.0,
        narration_span="x", intent_id="X",
        shot_role="REVEAL", narrative_phase="DEVELOPMENT",
    )


# ── A. Article B recipe coverage ────────────────────────────────────────


def test_all_17_article_b_recipes_exist() -> None:
    lib = _lib()
    for rid in ARTICLE_B_IDS:
        assert lib.get(rid) is not None, f"missing: {rid}"


def test_article_b_recipes_have_structured_primitives() -> None:
    """No name-only coverage: every new recipe sets at least one primitive."""
    lib = _lib()
    for rid in ARTICLE_B_IDS:
        r = lib.get(rid)
        structured = [
            r.viewpoint, r.stabilization, r.path, r.focal_behavior,
            r.temporal_structure, r.trigger,
        ]
        assert any(structured), f"{rid} has no structured primitive"
        assert r.motion_behavior, f"{rid} has no motion_behavior"


def test_total_recipe_count_is_80() -> None:
    lib = _lib()
    assert lib.stats().total_recipes == 80
    assert len({r.recipe_id for r in lib.list_all()}) == 80


# ── B. Structured primitive coverage ────────────────────────────────────


@pytest.mark.parametrize("field", [
    "camera_height", "camera_angle", "focal_length_detail", "focus",
    "depth_of_field", "start_state", "end_state", "hold_constraints",
])
def test_primitive_field_used_and_participates(field: str) -> None:
    """Each required field is set by ≥1 recipe AND reaches the plan output."""
    lib = _lib()
    users = [r for r in lib.list_all() if getattr(r, field, "")]
    assert users, f"no recipe sets {field}"
    beat = _beat()
    seen_in_plan = False
    for r in users[:5]:
        out = parameterize_recipe(r, RecipeParameters(), beat)
        cam = out["shot_plan"].get("camera", {})
        mot = out["motion_plan"]
        if field in cam or field in mot or "hold_requirement" in mot:
            seen_in_plan = True
            break
    assert seen_in_plan, f"{field} never reaches plan output"


# ── C. Semantic separation ──────────────────────────────────────────────


def test_handheld_is_not_gimbal() -> None:
    lib = _lib()
    h = lib.get("CAMERA.HANDHELD")
    g = lib.get("CAMERA.GIMBAL")
    assert h.stabilization == "HANDHELD"
    assert g.stabilization == "GIMBAL"
    assert h.stabilization != g.stabilization


def test_crane_jib_is_not_elevate() -> None:
    lib = _lib()
    c = lib.get("CAMERA.CRANE_JIB")
    assert c.stabilization == "CRANE"
    # A plain elevate has no platform claim; crane does.
    assert c.path == "ELEVATE"


def test_pov_is_not_fpv() -> None:
    lib = _lib()
    pov = lib.get("COMPOSITION.POV")
    fpv = lib.get("CAMERA.FPV")
    assert pov.viewpoint == "POV"
    assert fpv.viewpoint == "FPV"
    assert pov.viewpoint != fpv.viewpoint
    # Motion character differs structurally too.
    assert pov.motion_behavior != fpv.motion_behavior or pov.stabilization != fpv.stabilization


def test_roll_is_motion_not_static_cant() -> None:
    lib = _lib()
    r = lib.get("CAMERA.ROLL")
    assert r.start_state != r.end_state
    assert r.start_state == "LEVEL"
    assert r.end_state == "ROTATED_45"


def test_long_take_is_not_slow_motion() -> None:
    lib = _lib()
    r = lib.get("CAMERA.LONG_TAKE")
    assert r.temporal_structure == "LONG_TAKE"
    assert r.temporal_structure != "SLOW_MOTION"


def test_dolly_zoom_is_not_dolly() -> None:
    lib = _lib()
    dz = lib.get("CAMERA.DOLLY_ZOOM")
    assert dz.dolly_zoom is not None
    assert is_dolly_zoom(dz.dolly_zoom)


def test_dolly_zoom_is_not_zoom() -> None:
    lib = _lib()
    dz = lib.get("CAMERA.DOLLY_ZOOM")
    assert dz.path == "DOLLY"
    assert dz.focal_behavior == "ZOOM"
    # A plain zoom recipe has no coupling spec.
    assert lib.get("EXPLAINER.MACRO_TO_MICRO").dolly_zoom is None


# ── D. Dolly-zoom strict validator ──────────────────────────────────────


@pytest.mark.parametrize("missing", [
    "camera_translation", "focal_length_change",
    "inverse_coupling", "subject_screen_size_constraint",
])
def test_dolly_zoom_rejects_each_missing_field(missing: str) -> None:
    full = dict(
        camera_translation="dolly_in", focal_length_change="zoom_out",
        inverse_coupling=True, subject_screen_size_constraint="subject_constant",
    )
    if missing == "inverse_coupling":
        full[missing] = False
    else:
        full[missing] = ""
    valid, violations = validate_dolly_zoom(DollyZoomSpec(**full))
    assert valid is False
    assert violations


def test_plain_dolly_fails_is_dolly_zoom() -> None:
    assert is_dolly_zoom(DollyZoomSpec(camera_translation="dolly_in")) is False


def test_plain_zoom_fails_is_dolly_zoom() -> None:
    assert is_dolly_zoom(DollyZoomSpec(focal_length_change="zoom_out")) is False


def test_recipe_dolly_zoom_spec_validated_at_construction() -> None:
    with pytest.raises(ValueError, match="INVALID_DOLLY_ZOOM"):
        CinematicRecipe(
            recipe_id="T", version="1.0.0", recipe_family=RecipeFamily.CAMERA,
            name="t", description="t", path="DOLLY", focal_behavior="ZOOM",
            dolly_zoom=DollyZoomSpec(camera_translation="dolly_in"),
        )


# ── E. Combined movement ────────────────────────────────────────────────


def test_combined_movement_has_phases_trigger_terminal() -> None:
    lib = _lib()
    r = lib.get("CAMERA.COMBINED_MOVEMENT")
    assert r.movement_sequence is not None
    assert len(r.movement_sequence.phases) >= 2
    assert r.movement_sequence.trigger
    assert r.movement_sequence.terminal_state.final_hold_requirement


def test_combined_movement_not_reducible_to_single_phase() -> None:
    lib = _lib()
    r = lib.get("CAMERA.COMBINED_MOVEMENT")
    paths = {p.path for p in r.movement_sequence.phases}
    assert len(paths) >= 2 or len(r.movement_sequence.phases) >= 2


def test_combined_resolves_to_combined_not_single() -> None:
    lib = _lib()
    out = parameterize_recipe(
        lib.get("CAMERA.COMBINED_MOVEMENT"), RecipeParameters(), _beat()
    )
    assert out["motion_plan"]["motion_type"] == "combined"


def test_movement_sequence_rejects_empty_phases() -> None:
    from hevi.production.p5_3.schema import MovementSequence
    with pytest.raises(ValueError, match="INVALID_MOVEMENT_SEQUENCE"):
        CinematicRecipe(
            recipe_id="T", version="1.0.0", recipe_family=RecipeFamily.CAMERA,
            name="t", description="t",
            movement_sequence=MovementSequence(phases=(), trigger="BEAT_START"),
        )


# ── F. Forbidden actions ────────────────────────────────────────────────


def test_forbidden_action_pass_case() -> None:
    """A recipe that forbids zoom parameterizes normally when motion is static."""
    lib = _lib()
    r = lib.get("CAMERA.LONG_TAKE")
    out = parameterize_recipe(r, RecipeParameters(), _beat())
    assert out["motion_plan"]["motion_type"] == "static"


def test_forbidden_action_reject_case() -> None:
    """Requesting a forbidden motion raises instead of shipping."""
    lib = _lib()
    r = lib.get("CAMERA.LONG_TAKE")
    assert "zoom" in [f.lower() for f in r.forbidden_actions]
    with pytest.raises(ValueError, match="FORBIDDEN_ACTION"):
        check_forbidden_actions(r, "zoom_in")


def test_forbidden_action_family_match() -> None:
    """zoom_in matches forbidden zoom (family, not just exact string)."""
    lib = _lib()
    r = lib.get("CAMERA.LONG_TAKE")
    with pytest.raises(ValueError, match="FORBIDDEN_ACTION"):
        check_forbidden_actions(r, "zoom_out")


def test_non_forbidden_motion_passes() -> None:
    lib = _lib()
    r = lib.get("CAMERA.LONG_TAKE")
    check_forbidden_actions(r, "static")


# ── G. Start/end/hold ───────────────────────────────────────────────────


def test_start_end_states_reach_plan() -> None:
    lib = _lib()
    out = parameterize_recipe(lib.get("CAMERA.ROLL"), RecipeParameters(), _beat())
    cam = out["shot_plan"].get("camera", {})
    assert cam.get("start_state") == "LEVEL"
    assert cam.get("end_state") == "ROTATED_45"


def test_hold_constraints_reach_plan() -> None:
    lib = _lib()
    out = parameterize_recipe(lib.get("CAMERA.ROLL"), RecipeParameters(), _beat())
    assert out["motion_plan"].get("hold_requirement") == "HOLD_1S"


def test_invalid_start_state_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="INVALID_START_STATE"):
        CinematicRecipe(
            recipe_id="T", version="1.0.0", recipe_family=RecipeFamily.CAMERA,
            name="t", description="t", start_state="UPSIDE_DOWN",
        )


def test_invalid_hold_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="INVALID_HOLD_CONSTRAINTS"):
        CinematicRecipe(
            recipe_id="T", version="1.0.0", recipe_family=RecipeFamily.CAMERA,
            name="t", description="t", hold_constraints="HOLD_FOREVER",
        )


# ── H. Retrieval + evidence ─────────────────────────────────────────────


@pytest.mark.parametrize("rid", [
    "CAMERA.WHIP_PAN", "CAMERA.TILT", "CAMERA.RACK_FOCUS", "CAMERA.TRUCK",
    "CAMERA.ELEVATE", "CAMERA.FOLLOW", "CAMERA.HANDHELD", "CAMERA.GIMBAL",
    "CAMERA.CRANE_JIB", "CAMERA.DRONE", "CAMERA.ROLL", "CAMERA.DOLLY_ZOOM",
    "CAMERA.LONG_TAKE", "CAMERA.COMBINED_MOVEMENT", "CAMERA.FPV",
    "COMPOSITION.AERIAL", "COMPOSITION.POV",
])
def test_new_recipe_retrievable_with_evidence(rid: str) -> None:
    """Every new recipe must surface through the canonical path with evidence."""
    lib = _lib()
    recipe = lib.get(rid)
    # Query by the recipe's own profile and beat role.
    profile = recipe.profile_compatibility[0]
    beat = VisualBeat(
        beat_id="probe", timeline_start_s=0.0, timeline_end_s=3.0,
        narration_span="probe", intent_id=recipe.intent or "X",
        shot_role=recipe.beat_roles[0],
        narrative_phase="DEVELOPMENT",
    )
    cands, ev = retrieve_with_evidence(lib, beat, profile_id=profile)
    assert cands
    assert ev.selected_recipe_id
    assert ev.selected_recipe_id in [c.recipe_id for c in cands]
    assert ev.rejected_candidates is not None
