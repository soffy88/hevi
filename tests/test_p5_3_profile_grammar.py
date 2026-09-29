"""HEVI P5.3 — profile grammar tests: 4 profiles have distinct preferences."""

from __future__ import annotations

from hevi.production.p5_3.profile_grammar import is_profile_distinct, profile_recipe_preferences


def test_all_four_profiles_have_preferences() -> None:
    for profile in ("EMOTIONAL_BOOK_REVIEW", "WHITEBOARD_EXPLAINER", "SCIENCE_EXPLAINER", "HISTORICAL_NARRATIVE"):
        prefs = profile_recipe_preferences(profile)
        assert prefs["preferred_recipes"], f"{profile} has no preferred recipes"
        assert prefs["preferred_families"], f"{profile} has no preferred families"


def test_profiles_are_distinct() -> None:
    profiles = ("EMOTIONAL_BOOK_REVIEW", "WHITEBOARD_EXPLAINER", "SCIENCE_EXPLAINER", "HISTORICAL_NARRATIVE")
    recipe_sets = [set(profile_recipe_preferences(p)["preferred_recipes"]) for p in profiles]
    # Each pair of profiles should differ in at least one preferred recipe
    for i in range(len(profiles)):
        for j in range(i + 1, len(profiles)):
            assert recipe_sets[i] != recipe_sets[j], f"{profiles[i]} and {profiles[j]} have identical preferences"


def test_emotional_profile_prefers_emotional_family() -> None:
    prefs = profile_recipe_preferences("EMOTIONAL_BOOK_REVIEW")
    assert "EMOTIONAL" in prefs["preferred_families"]


def test_whiteboard_profile_prefers_explainer_family() -> None:
    prefs = profile_recipe_preferences("WHITEBOARD_EXPLAINER")
    assert "EXPLAINER" in prefs["preferred_families"]


def test_science_profile_prefers_evidence_family() -> None:
    prefs = profile_recipe_preferences("SCIENCE_EXPLAINER")
    assert "EVIDENCE" in prefs["preferred_families"]


def test_historical_profile_prefers_evidence_family() -> None:
    prefs = profile_recipe_preferences("HISTORICAL_NARRATIVE")
    assert "EVIDENCE" in prefs["preferred_families"]


def test_unknown_profile_returns_empty() -> None:
    prefs = profile_recipe_preferences("UNKNOWN_PROFILE")
    assert prefs["preferred_recipes"] == []
    assert prefs["preferred_families"] == []


def test_is_profile_distinct() -> None:
    assert is_profile_distinct("EMOTIONAL_BOOK_REVIEW") is True
    assert is_profile_distinct("UNKNOWN") is False
