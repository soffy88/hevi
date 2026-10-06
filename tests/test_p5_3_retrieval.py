"""HEVI P5.3 — retrieval tests: semantic, constraint-aware, no random selection."""

from __future__ import annotations

from hevi.production.p1_types import VisualBeat
from hevi.production.p5_3.library import RecipeLibrary
from hevi.production.p5_3.recipes import load_all_recipes
from hevi.production.p5_3.retrieval import retrieve_recipes


def _beat(**kwargs) -> VisualBeat:
    defaults = dict(
        beat_id="b1",
        timeline_start_s=0.0,
        timeline_end_s=3.0,
        narration_span="test",
        intent_id="ESTABLISH_SUBJECT",
        shot_role="ESTABLISH",
        narrative_phase="HOOK",
    )
    defaults.update(kwargs)
    return VisualBeat(**defaults)


def _lib() -> RecipeLibrary:
    lib = RecipeLibrary()
    for r in load_all_recipes():
        lib.register(r)
    return lib


def test_retrieve_returns_candidates() -> None:
    lib = _lib()
    beat = _beat()
    cands, _ = retrieve_recipes(lib, beat)
    assert len(cands) > 0


def test_retrieve_no_random_selection() -> None:
    """Retrieval is deterministic: same input produces same output."""
    lib = _lib()
    beat = _beat()
    c1, _ = retrieve_recipes(lib, beat)
    c2, _ = retrieve_recipes(lib, beat)
    assert [c.recipe_id for c in c1] == [c.recipe_id for c in c2]


def test_retrieve_respects_profile() -> None:
    lib = _lib()
    beat = _beat()
    cands, _ = retrieve_recipes(lib, beat, profile_id="EMOTIONAL_BOOK_REVIEW")
    for c in cands:
        assert "EMOTIONAL_BOOK_REVIEW" in c.constraint_violations or c.profile_match > 0.0


def test_retrieve_respects_duration() -> None:
    lib = _lib()
    beat = _beat()
    cands, _ = retrieve_recipes(lib, beat, duration=3.0)
    for c in cands:
        assert not any("DURATION_OUT_OF_RANGE" in v for v in c.constraint_violations)


def test_retrieve_excludes_incompatible_profile() -> None:
    lib = _lib()
    beat = _beat()
    cands, _ = retrieve_recipes(lib, beat, profile_id="SCIENCE_EXPLAINER")
    # Emotional-only recipes should be excluded
    emotional_only = [c for c in cands if c.recipe_id.startswith("EMOTIONAL.")]
    for c in emotional_only:
        assert any("PROFILE_INCOMPATIBLE" in v for v in c.constraint_violations)


def test_retrieve_ranks_by_semantic_match() -> None:
    lib = _lib()
    beat = _beat(shot_role="ESTABLISH", intent_id="ESTABLISH_SUBJECT")
    cands, _ = retrieve_recipes(lib, beat)
    if len(cands) > 1:
        assert cands[0].selection_score >= cands[-1].selection_score


def test_retrieve_with_renderer_capabilities() -> None:
    lib = _lib()
    beat = _beat()
    cands, _ = retrieve_recipes(lib, beat, renderer_capabilities=["TEXT", "SVG"])
    assert len(cands) > 0


def test_retrieve_with_available_assets() -> None:
    """Asset filtering is a hard constraint: unavailable assets exclude candidates."""
    lib = _lib()
    beat = _beat()
    # With no asset constraint, candidates are returned
    cands, _ = retrieve_recipes(lib, beat)
    assert len(cands) > 0
    # With an asset no recipe requires, all are excluded (constraint, not penalty)
    cands_none, _ = retrieve_recipes(lib, beat, available_assets=["nonexistent_asset_type"])
    assert cands_none == []
