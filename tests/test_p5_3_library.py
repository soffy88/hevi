"""HEVI P5.3 — RecipeLibrary tests: single authority, no duplicate registries."""

from __future__ import annotations

import pytest

from hevi.production.p5_3.library import RecipeLibrary
from hevi.production.p5_3.schema import (
    CinematicRecipe,
    QualificationState,
    RecipeFamily,
    RecipeUsageRecord,
)


def _recipe(recipe_id: str, **kwargs) -> CinematicRecipe:
    defaults = dict(
        recipe_id=recipe_id,
        version="1.0.0",
        recipe_family=RecipeFamily.COMPOSITION,
        name=f"Recipe {recipe_id}",
        description=f"Description for {recipe_id}",
    )
    defaults.update(kwargs)
    return CinematicRecipe(**defaults)


def test_register_and_get() -> None:
    lib = RecipeLibrary()
    r = _recipe("COMPOSITION.CENTERED_HERO")
    lib.register(r)
    assert lib.get("COMPOSITION.CENTERED_HERO") is not None
    assert lib.get("COMPOSITION.CENTERED_HERO").name == "Recipe COMPOSITION.CENTERED_HERO"


def test_register_duplicate_version_raises() -> None:
    lib = RecipeLibrary()
    lib.register(_recipe("X"))
    with pytest.raises(ValueError, match="RECIPE_VERSION_IMMUTABLE"):
        lib.register(_recipe("X"))


def test_get_specific_version() -> None:
    lib = RecipeLibrary()
    lib.register(_recipe("X", version="1.0.0"))
    lib.register(_recipe("X", version="2.0.0"))
    assert lib.get_version("X", "1.0.0").version == "1.0.0"
    assert lib.get_version("X", "2.0.0").version == "2.0.0"


def test_get_latest_version() -> None:
    lib = RecipeLibrary()
    lib.register(_recipe("X", version="1.0.0"))
    lib.register(_recipe("X", version="2.0.0"))
    assert lib.get("X").version == "2.0.0"


def test_search_by_family() -> None:
    lib = RecipeLibrary()
    lib.register(_recipe("COMPOSITION.A", recipe_family=RecipeFamily.COMPOSITION))
    lib.register(_recipe("CAMERA.B", recipe_family=RecipeFamily.CAMERA))
    results = lib.search(family=RecipeFamily.COMPOSITION)
    assert len(results) == 1
    assert results[0].recipe_id == "COMPOSITION.A"


def test_search_by_profile() -> None:
    lib = RecipeLibrary()
    lib.register(_recipe("X", profile_compatibility=["EMOTIONAL_BOOK_REVIEW"]))
    lib.register(_recipe("Y", profile_compatibility=["SCIENCE_EXPLAINER"]))
    results = lib.search(profile="EMOTIONAL_BOOK_REVIEW")
    assert len(results) == 1
    assert results[0].recipe_id == "X"


def test_search_by_duration() -> None:
    lib = RecipeLibrary()
    lib.register(_recipe("X", duration_range=(2.0, 5.0)))
    lib.register(_recipe("Y", duration_range=(10.0, 20.0)))
    results = lib.search(duration=3.0)
    assert len(results) == 1
    assert results[0].recipe_id == "X"


def test_search_by_qualification_state() -> None:
    lib = RecipeLibrary()
    lib.register(_recipe("X", qualification_state=QualificationState.EXPERIMENTAL))
    lib.register(_recipe("Y", qualification_state=QualificationState.QUALIFIED))
    results = lib.search(qualification_state=QualificationState.QUALIFIED)
    assert len(results) == 1
    assert results[0].recipe_id == "Y"


def test_filter_excludes_constraint_violations() -> None:
    lib = RecipeLibrary()
    lib.register(_recipe("X", profile_compatibility=["EMOTIONAL_BOOK_REVIEW"]))
    lib.register(_recipe("Y", profile_compatibility=["SCIENCE_EXPLAINER"]))
    results = lib.filter(lib.list_all(), profile="EMOTIONAL_BOOK_REVIEW")
    assert len(results) == 1
    assert results[0].recipe_id == "X"


def test_rank_candidates_excludes_violations() -> None:
    lib = RecipeLibrary()
    from hevi.production.p5_3.schema import RecipeCandidate
    c1 = RecipeCandidate(recipe_id="X", version="1.0.0", semantic_match=0.9, constraint_violations=[])
    c2 = RecipeCandidate(recipe_id="Y", version="1.0.0", semantic_match=0.95, constraint_violations=["PROFILE_INCOMPATIBLE"])
    ranked = lib.rank_candidates([c1, c2])
    assert len(ranked) == 1
    assert ranked[0].recipe_id == "X"


def test_rank_candidates_orders_by_score() -> None:
    lib = RecipeLibrary()
    from hevi.production.p5_3.schema import RecipeCandidate
    c1 = RecipeCandidate(recipe_id="X", version="1.0.0", semantic_match=0.5)
    c2 = RecipeCandidate(recipe_id="Y", version="1.0.0", semantic_match=0.9)
    ranked = lib.rank_candidates([c1, c2])
    assert ranked[0].recipe_id == "Y"
    assert ranked[1].recipe_id == "X"


def test_list_family() -> None:
    lib = RecipeLibrary()
    lib.register(_recipe("COMPOSITION.A", recipe_family=RecipeFamily.COMPOSITION))
    lib.register(_recipe("COMPOSITION.B", recipe_family=RecipeFamily.COMPOSITION))
    lib.register(_recipe("CAMERA.C", recipe_family=RecipeFamily.CAMERA))
    assert len(lib.list_family(RecipeFamily.COMPOSITION)) == 2
    assert len(lib.list_family(RecipeFamily.CAMERA)) == 1


def test_list_qualified() -> None:
    lib = RecipeLibrary()
    lib.register(_recipe("X", qualification_state=QualificationState.EXPERIMENTAL))
    lib.register(_recipe("Y", qualification_state=QualificationState.QUALIFIED))
    assert len(lib.list_qualified()) == 1


def test_record_usage_and_outcome() -> None:
    lib = RecipeLibrary()
    lib.register(_recipe("X"))
    lib.record_usage(RecipeUsageRecord(
        recipe_id="X", recipe_version="1.0.0", profile="EMOTIONAL_BOOK_REVIEW",
        content_id="c1", beat_role="ESTABLISH",
    ))
    lib.record_outcome("X", "1.0.0", {"status": "PASS"})
    assert len(lib._usage_records) == 1
    assert len(lib.get_outcomes("X", "1.0.0")) == 1


def test_stats() -> None:
    lib = RecipeLibrary()
    lib.register(_recipe("COMPOSITION.A", recipe_family=RecipeFamily.COMPOSITION))
    lib.register(_recipe("CAMERA.B", recipe_family=RecipeFamily.CAMERA))
    stats = lib.stats()
    assert stats.total_recipes == 2
    assert stats.family_counts["COMPOSITION"] == 1
    assert stats.family_counts["CAMERA"] == 1


def test_save_and_load(tmp_path) -> None:
    lib = RecipeLibrary()
    lib.register(_recipe("X", intent="TEST"))
    path = tmp_path / "lib.json"
    lib.save(path)
    lib2 = RecipeLibrary.load(path)
    assert lib2.get("X").intent == "TEST"
    assert lib2.stats().total_recipes == 1


def test_no_duplicate_registry() -> None:
    """The library is the only registry. No SkillRegistry, MotionRegistry, or ShotRegistry."""
    import hevi.production.p5_3 as p53
    assert not hasattr(p53, "SkillRegistry")
    assert not hasattr(p53, "MotionRegistry")
    assert not hasattr(p53, "ShotRegistry")
