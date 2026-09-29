"""HEVI P5.3 — parameterization tests: Recipe + Parameters -> suggestions."""

from __future__ import annotations

from hevi.production.p1_types import VisualBeat
from hevi.production.p5_3.library import RecipeLibrary
from hevi.production.p5_3.parameterization import parameterize_recipe
from hevi.production.p5_3.recipes import load_all_recipes
from hevi.production.p5_3.schema import RecipeParameters


def _beat() -> VisualBeat:
    return VisualBeat(
        beat_id="b1", timeline_start_s=0.0, timeline_end_s=3.0,
        narration_span="test", intent_id="ESTABLISH_SUBJECT",
        shot_role="ESTABLISH", narrative_phase="HOOK",
    )


def _lib() -> RecipeLibrary:
    lib = RecipeLibrary()
    for r in load_all_recipes():
        lib.register(r)
    return lib


def test_parameterize_returns_shot_and_motion_suggestions() -> None:
    lib = _lib()
    r = lib.get("COMPOSITION.CENTERED_HERO")
    result = parameterize_recipe(r, RecipeParameters(duration=4.0), _beat())
    assert "shot_plan" in result
    assert "motion_plan" in result


def test_parameterize_shot_size_from_camera_behavior() -> None:
    lib = _lib()
    r = lib.get("CAMERA.DETAIL_TO_CONTEXT")
    result = parameterize_recipe(r, RecipeParameters(), _beat())
    assert result["shot_plan"]["shot_size"] in ("wide", "medium", "closeup", "extreme_closeup")


def test_parameterize_motion_type_from_motion_behavior() -> None:
    lib = _lib()
    r = lib.get("CAMERA.SLOW_PUSH_IN")
    result = parameterize_recipe(r, RecipeParameters(), _beat())
    assert result["motion_plan"]["motion_type"] != "static"


def test_parameterize_respects_duration_override() -> None:
    lib = _lib()
    r = lib.get("COMPOSITION.CENTERED_HERO")
    result = parameterize_recipe(r, RecipeParameters(duration=7.0), _beat())
    assert result["shot_plan"]["duration_s"] == 7.0


def test_parameterize_uses_default_duration_when_not_specified() -> None:
    lib = _lib()
    r = lib.get("COMPOSITION.CENTERED_HERO")
    result = parameterize_recipe(r, RecipeParameters(), _beat())
    min_d, max_d = r.duration_range
    expected = (min_d + max_d) / 2.0
    assert abs(result["shot_plan"]["duration_s"] - expected) < 0.01


def test_parameterize_does_not_create_shot_plan() -> None:
    """P5.3 produces suggestions, not ShotPlan objects."""
    lib = _lib()
    r = lib.get("COMPOSITION.CENTERED_HERO")
    result = parameterize_recipe(r, RecipeParameters(duration=3.0), _beat())
    assert isinstance(result["shot_plan"], dict)
    assert "shot_id" not in result["shot_plan"]  # Not a ShotPlan


def test_parameterize_does_not_create_motion_plan() -> None:
    """P5.3 produces suggestions, not MotionPlan objects."""
    lib = _lib()
    r = lib.get("CAMERA.SLOW_PUSH_IN")
    result = parameterize_recipe(r, RecipeParameters(), _beat())
    assert isinstance(result["motion_plan"], dict)
    assert "motion_id" not in result["motion_plan"]  # Not a MotionPlan


def test_parameterize_all_recipes() -> None:
    """Every recipe can be parameterized without error."""
    lib = _lib()
    for r in lib.list_all():
        result = parameterize_recipe(r, RecipeParameters(duration=3.0), _beat())
        assert "shot_plan" in result
        assert "motion_plan" in result
