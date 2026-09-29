"""HEVI P5.3 — CreativeLedger integration and variety control tests."""

from __future__ import annotations

from hevi.production.creative_ledger import CreativeLedger
from hevi.production.p5_3.creative_integration import (
    compute_variety_score,
    is_semantic_correctness_overriding_variety,
    record_recipe_usage,
)
from hevi.production.p5_3.library import RecipeLibrary
from hevi.production.p5_3.recipes import load_all_recipes
from hevi.production.p5_3.schema import RecipeUsageRecord


def _lib() -> RecipeLibrary:
    lib = RecipeLibrary()
    for r in load_all_recipes():
        lib.register(r)
    return lib


def test_record_usage_integrates_with_creative_ledger() -> None:
    ledger = CreativeLedger()
    record = RecipeUsageRecord(
        recipe_id="COMPOSITION.CENTERED_HERO",
        recipe_version="1.0.0",
        profile="EMOTIONAL_BOOK_REVIEW",
        content_id="c1",
        beat_role="ESTABLISH",
    )
    record_recipe_usage(ledger, record)
    # The ledger should have recorded the usage
    assert len(ledger.all_shots()) > 0


def test_variety_score_decreases_with_repetition() -> None:
    lib = _lib()
    score_high = compute_variety_score(lib, "COMPOSITION.CENTERED_HERO", recent_recipe_ids=[])
    score_low = compute_variety_score(
        lib, "COMPOSITION.CENTERED_HERO",
        recent_recipe_ids=["COMPOSITION.CENTERED_HERO", "COMPOSITION.CENTERED_HERO"],
    )
    assert score_high.variety_score > score_low.variety_score


def test_variety_score_same_family() -> None:
    lib = _lib()
    score = compute_variety_score(
        lib, "COMPOSITION.CENTERED_HERO",
        recent_family_ids=["COMPOSITION", "COMPOSITION"],
    )
    assert score.same_family_frequency > 0.0


def test_semantic_correctness_overrides_variety() -> None:
    assert is_semantic_correctness_overriding_variety(0.9, 0.3) is True
    assert is_semantic_correctness_overriding_variety(0.3, 0.9) is False


def test_variety_never_sets_semantic_override() -> None:
    """Variety scoring must not set semantic_override to True."""
    lib = _lib()
    score = compute_variety_score(lib, "COMPOSITION.CENTERED_HERO")
    assert score.semantic_override is False
