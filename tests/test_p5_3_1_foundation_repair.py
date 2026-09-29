"""HEVI P5.3.1 — foundation repair regressions.

Each test pins one audit finding so it cannot regress. None of these tests
changes business behavior; they lock the repaired behavior in place.
"""

from __future__ import annotations

import pytest

from hevi.production.p1_types import VisualBeat
from hevi.production.p5_3.library import RecipeLibrary
from hevi.production.p5_3.parameterization import parameterize_recipe
from hevi.production.p5_3.recipes import load_all_recipes
from hevi.production.p5_3.retrieval import retrieve_recipes, retrieve_with_evidence
from hevi.production.p5_3.schema import (
    CinematicRecipe,
    DollyZoomSpec,
    MovementPhase,
    MovementSequence,
    RecipeFamily,
    RecipeParameters,
    TerminalState,
    is_dolly_zoom,
    validate_dolly_zoom,
)


def _lib() -> RecipeLibrary:
    lib = RecipeLibrary()
    for r in load_all_recipes():
        lib.register(r)
    return lib


def _beat() -> VisualBeat:
    return VisualBeat(
        beat_id="b1", timeline_start_s=0.0, timeline_end_s=3.0,
        narration_span="x", intent_id="ESTABLISH_SUBJECT",
        shot_role="ESTABLISH", narrative_phase="HOOK",
    )


# ── 1. Duplicate differentiated ─────────────────────────────────────────


def test_context_to_detail_is_a_dolly() -> None:
    lib = _lib()
    r = lib.get("CAMERA.CONTEXT_TO_DETAIL")
    assert r.path == "DOLLY"
    assert r.focal_behavior == "STATIC_FOCAL"


def test_macro_to_micro_is_a_zoom() -> None:
    lib = _lib()
    r = lib.get("EXPLAINER.MACRO_TO_MICRO")
    assert r.path == "STATIC_PATH"
    assert r.focal_behavior == "ZOOM"


def test_duplicate_pair_no_longer_shares_execution() -> None:
    lib = _lib()
    a = lib.get("CAMERA.CONTEXT_TO_DETAIL")
    b = lib.get("EXPLAINER.MACRO_TO_MICRO")
    assert (a.path, a.focal_behavior) != (b.path, b.focal_behavior)


def test_duplicate_fix_preserves_callers() -> None:
    """Same IDs, same families, same beats, still 63 recipes."""
    lib = _lib()
    assert lib.get("CAMERA.CONTEXT_TO_DETAIL").recipe_family is RecipeFamily.CAMERA
    assert lib.get("EXPLAINER.MACRO_TO_MICRO").recipe_family is RecipeFamily.EXPLAINER
    assert lib.stats().total_recipes == 63


# ── 2. map_trace not erased ─────────────────────────────────────────────


def test_map_trace_keeps_its_identity() -> None:
    lib = _lib()
    out = parameterize_recipe(
        lib.get("EVIDENCE.MAP_TRACE"), RecipeParameters(), _beat()
    )
    assert out["motion_plan"]["motion_type"] == "map_trace"


def test_map_trace_carries_capability_note() -> None:
    lib = _lib()
    out = parameterize_recipe(
        lib.get("EVIDENCE.MAP_TRACE"), RecipeParameters(), _beat()
    )
    note = out["motion_plan"].get("capability_limitation", "")
    assert "map_trace" in note


def test_static_recipes_gain_no_spurious_note() -> None:
    lib = _lib()
    out = parameterize_recipe(
        lib.get("CAMERA.STATIC_HOLD"), RecipeParameters(), _beat()
    )
    assert "capability_limitation" not in out["motion_plan"]


# ── 3. Selection evidence ───────────────────────────────────────────────


def test_evidence_path_matches_canonical_path() -> None:
    lib = _lib()
    beat = _beat()
    plain = retrieve_recipes(lib, beat, profile_id="EMOTIONAL_BOOK_REVIEW")
    ranked, _ = retrieve_with_evidence(lib, beat, profile_id="EMOTIONAL_BOOK_REVIEW")
    assert [c.recipe_id for c in plain] == [c.recipe_id for c in ranked]


def test_evidence_answers_why_this() -> None:
    lib = _lib()
    _, ev = retrieve_with_evidence(lib, _beat(), profile_id="EMOTIONAL_BOOK_REVIEW")
    assert ev.selected_recipe_id
    assert ev.selected_version == "1.0.0"
    assert ev.selection_factors["selection_score"] > 0
    assert "semantic_match" in ev.selection_factors


def test_evidence_answers_why_not() -> None:
    lib = _lib()
    _, ev = retrieve_with_evidence(lib, _beat(), profile_id="EMOTIONAL_BOOK_REVIEW")
    assert ev.rejected_candidates
    assert set(ev.rejected_candidates) == set(ev.rejection_reasons)
    assert ev.selected_recipe_id not in ev.rejected_candidates


def test_evidence_is_deterministic() -> None:
    lib = _lib()
    beat = _beat()
    _, e1 = retrieve_with_evidence(lib, beat, profile_id="EMOTIONAL_BOOK_REVIEW")
    _, e2 = retrieve_with_evidence(lib, beat, profile_id="EMOTIONAL_BOOK_REVIEW")
    assert e1.selected_recipe_id == e2.selected_recipe_id
    assert e1.candidate_recipe_ids == e2.candidate_recipe_ids
    assert e1.rejection_reasons == e2.rejection_reasons


# ── 4. Validated primitives ─────────────────────────────────────────────


@pytest.mark.parametrize("field,value", [
    ("viewpoint", "POV"), ("viewpoint", "FPV"),
    ("stabilization", "TRIPOD"), ("stabilization", "HANDHELD"), ("stabilization", "GIMBAL"),
    ("path", "PAN"), ("path", "TILT"), ("path", "DOLLY"), ("path", "TRUCK"),
    ("path", "ELEVATE"), ("path", "ORBIT"), ("path", "FOLLOW"),
    ("focal_behavior", "ZOOM"), ("focal_behavior", "STATIC_FOCAL"),
    ("temporal_structure", "SINGLE_TAKE"), ("temporal_structure", "LONG_TAKE"),
    ("trigger", "BEAT_START"), ("trigger", "NARRATION_CUE"),
])
def test_valid_primitives_accepted(field: str, value: str) -> None:
    r = CinematicRecipe(
        recipe_id="T", version="1.0.0", recipe_family=RecipeFamily.CAMERA,
        name="t", description="t", **{field: value},
    )
    assert getattr(r, field) == value


@pytest.mark.parametrize("field,value", [
    ("viewpoint", "SIDEWAYS"), ("stabilization", "DUCT_TAPE"),
    ("path", "TELEPORT"), ("focal_behavior", "ENLARGE"),
    ("temporal_structure", "FOREVER"), ("trigger", "WHENEVER"),
])
def test_invalid_primitives_rejected(field: str, value: str) -> None:
    with pytest.raises(ValueError, match=f"INVALID_{field.upper()}"):
        CinematicRecipe(
            recipe_id="T", version="1.0.0", recipe_family=RecipeFamily.CAMERA,
            name="t", description="t", **{field: value},
        )


def test_tripod_is_not_static() -> None:
    """TRIPOD is a platform; STATIC is a camera state. Different facts."""
    r = CinematicRecipe(
        recipe_id="T", version="1.0.0", recipe_family=RecipeFamily.CAMERA,
        name="t", description="t", stabilization="TRIPOD", path="STATIC_PATH",
    )
    assert r.stabilization == "TRIPOD"
    assert r.path == "STATIC_PATH"


def test_long_take_is_not_slow_motion() -> None:
    r = CinematicRecipe(
        recipe_id="T", version="1.0.0", recipe_family=RecipeFamily.CAMERA,
        name="t", description="t", temporal_structure="LONG_TAKE",
    )
    assert r.temporal_structure == "LONG_TAKE"
    assert r.temporal_structure != "SLOW_MOTION"


# ── 5. Dolly-zoom foundation ────────────────────────────────────────────


def test_incomplete_dolly_zoom_rejected() -> None:
    valid, violations = validate_dolly_zoom(DollyZoomSpec())
    assert valid is False
    assert len(violations) == 4


def test_complete_dolly_zoom_accepted() -> None:
    spec = DollyZoomSpec(
        camera_translation="dolly_in",
        focal_length_change="zoom_out",
        inverse_coupling=True,
        subject_screen_size_constraint="subject_constant",
    )
    assert is_dolly_zoom(spec) is True


def test_plain_dolly_is_not_dolly_zoom() -> None:
    spec = DollyZoomSpec(camera_translation="dolly_in")
    assert is_dolly_zoom(spec) is False


def test_plain_zoom_is_not_dolly_zoom() -> None:
    spec = DollyZoomSpec(focal_length_change="zoom_out")
    assert is_dolly_zoom(spec) is False


# ── 6. Combined movement foundation ─────────────────────────────────────


def test_movement_sequence_structure() -> None:
    seq = MovementSequence(
        phases=(
            MovementPhase(camera_action="push_in", path="DOLLY",
                          velocity_profile="ease_in", hold_constraints="hold_1s"),
            MovementPhase(camera_action="hold", path="STATIC_PATH",
                          velocity_profile="linear", hold_constraints="hold_2s"),
        ),
        trigger="BEAT_START",
        terminal_state=TerminalState(
            final_camera_state="static",
            final_composition="closeup",
            final_hold_requirement="hold_2s",
        ),
    )
    assert len(seq.phases) == 2
    assert seq.trigger == "BEAT_START"
    assert seq.terminal_state.final_hold_requirement == "hold_2s"


def test_terminal_state_fields() -> None:
    ts = TerminalState(
        final_camera_state="static",
        final_composition="centered",
        final_hold_requirement="hold_2s",
    )
    assert ts.final_camera_state == "static"
    assert ts.final_composition == "centered"
    assert ts.final_hold_requirement == "hold_2s"
