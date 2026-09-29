"""HEVI P5.3 — recipe set tests: count, quality, no padding."""

from __future__ import annotations

from collections import Counter

from hevi.production.p5_3.recipes import load_all_recipes
from hevi.production.p5_3.schema import RecipeFamily


def test_recipe_count_at_least_60() -> None:
    recipes = load_all_recipes()
    assert len(recipes) >= 60


def test_all_families_present() -> None:
    recipes = load_all_recipes()
    families = {r.recipe_family for r in recipes}
    assert len(families) == 8


def test_family_minimums() -> None:
    recipes = load_all_recipes()
    counts = Counter(r.recipe_family for r in recipes)
    assert counts[RecipeFamily.COMPOSITION] >= 8
    assert counts[RecipeFamily.CAMERA] >= 8
    assert counts[RecipeFamily.EVIDENCE] >= 8
    assert counts[RecipeFamily.EXPLAINER] >= 8
    assert counts[RecipeFamily.EMOTIONAL] >= 6
    assert counts[RecipeFamily.PRESENTER] >= 6
    assert counts[RecipeFamily.PRODUCT] >= 8
    assert counts[RecipeFamily.DATA] >= 8


def test_no_duplicate_recipe_ids() -> None:
    recipes = load_all_recipes()
    ids = [r.recipe_id for r in recipes]
    assert len(ids) == len(set(ids))


def test_no_prompt_only_recipes() -> None:
    """Every recipe must have structured content, not just a prompt hint."""
    recipes = load_all_recipes()
    for r in recipes:
        assert r.name, f"{r.recipe_id} has no name"
        assert r.description, f"{r.recipe_id} has no description"
        assert r.composition or r.camera_behavior or r.motion_behavior, (
            f"{r.recipe_id} has no structured behavior"
        )


def test_all_recipes_have_provenance() -> None:
    recipes = load_all_recipes()
    for r in recipes:
        assert r.source_provenance.origin, f"{r.recipe_id} has no provenance"


def test_all_recipes_have_renderer_requirements() -> None:
    recipes = load_all_recipes()
    for r in recipes:
        assert r.renderer_requirements or r.renderer_preferences, (
            f"{r.recipe_id} has no renderer requirements"
        )


def test_no_renderer_lock_in() -> None:
    """No recipe contains renderer-specific implementation."""
    recipes = load_all_recipes()
    forbidden = ["<div", "<span", "className", "useState", "useEffect", "gsap", "remotion", "ffmpeg -"]
    for r in recipes:
        text = f"{r.composition} {r.camera_behavior} {r.motion_behavior} {r.prompt_hint}"
        for f in forbidden:
            assert f not in text.lower(), f"{r.recipe_id} contains renderer-specific: {f}"


def test_all_recipes_experimental_initially() -> None:
    recipes = load_all_recipes()
    for r in recipes:
        assert r.qualification_state.value == "EXPERIMENTAL"


def test_recipe_ids_are_namespaced() -> None:
    recipes = load_all_recipes()
    for r in recipes:
        assert "." in r.recipe_id, f"{r.recipe_id} is not namespaced"
        family = r.recipe_id.split(".")[0]
        assert family == r.recipe_family.value, f"{r.recipe_id} family mismatch"
