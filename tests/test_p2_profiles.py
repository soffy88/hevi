"""P2 Production Profiles — fast unit tests (no TTS/render)."""

from __future__ import annotations

from hevi.production.p2_pipeline import build_creative_direction, select_profile
from hevi.production.p2_profiles import get_registry
from hevi.production.p2_types import ProfileFingerprint


def test_registry_has_four_profiles() -> None:
    reg = get_registry()
    ids = sorted(p.profile_id for p in reg.list_profiles())
    assert ids == [
        "EMOTIONAL_BOOK_REVIEW",
        "HISTORICAL_NARRATIVE",
        "SCIENCE_EXPLAINER",
        "WHITEBOARD_EXPLAINER",
    ]


def test_registry_validate_all() -> None:
    reg = get_registry()
    for p in reg.list_profiles():
        ok, errors = reg.validate(p.profile_id, p.profile_version)
        assert ok, errors


def test_auto_selection_book() -> None:
    pid, _reason, conf = select_profile(None, "This book about grief and solitude changed me")
    assert pid == "EMOTIONAL_BOOK_REVIEW"
    assert conf > 0


def test_auto_selection_whiteboard() -> None:
    pid, _reason, _conf = select_profile(None, "Draw the process step by step with arrows and diagrams")
    assert pid == "WHITEBOARD_EXPLAINER"


def test_auto_selection_science() -> None:
    pid, _reason, _conf = select_profile(None, "Black hole gravity orbit nasa accretion")
    assert pid == "SCIENCE_EXPLAINER"


def test_auto_selection_history() -> None:
    pid, _reason, _conf = select_profile(None, "In the seventh century Tang dynasty empire timeline")
    assert pid == "HISTORICAL_NARRATIVE"


def test_auto_selection_ambiguous_needs_selection() -> None:
    pid, _reason, conf = select_profile(None, "hello world")
    assert pid == "NEEDS_SELECTION"
    assert conf == 0.0


def test_explicit_selection_wins() -> None:
    pid, reason, conf = select_profile("SCIENCE_EXPLAINER", "a book about grief")
    assert pid == "SCIENCE_EXPLAINER"
    assert reason == "explicit_request"
    assert conf == 1.0


def test_creative_direction_carries_lineage() -> None:
    reg = get_registry()
    profile = reg.resolve("SCIENCE_EXPLAINER")
    assert profile is not None
    plan = build_creative_direction(profile, "black hole orbit", "test")
    assert plan.profile_id == "SCIENCE_EXPLAINER"
    assert plan.lineage == ("SCIENCE_EXPLAINER@v1.0",)


def test_fingerprint_distinctness() -> None:
    a = ProfileFingerprint(profile_id="A", profile_version="1.0", shot_role_histogram={"ESTABLISH": 3, "PAYOFF": 1})
    b = ProfileFingerprint(profile_id="B", profile_version="1.0", shot_role_histogram={"EXPLAIN": 3, "DETAIL": 1})
    assert a.distinct_from(b)
    assert not a.distinct_from(a)


def test_no_second_pipeline_module() -> None:
    import hevi.production.p1_pipeline as p1
    import hevi.production.p2_pipeline as p2

    assert hasattr(p1, "run_p1_production")
    assert hasattr(p2, "run_p2_production")
    # P2 must delegate to P1, not duplicate the orchestrator
    import inspect

    src = inspect.getsource(p2.run_p2_production)
    assert "run_p1_production" in src
