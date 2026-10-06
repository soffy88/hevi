"""HEVI P5.4 — Evidence Authority Closure: EVIDENCE=MANDATORY.

The production retrieval path (retrieve_recipes) must ALWAYS return a
RecipeSelectionEvidence. No production selection without evidence.
"""

from __future__ import annotations

from hevi.production.p1_types import VisualBeat
from hevi.production.p5_3.library import RecipeLibrary
from hevi.production.p5_3.recipes import load_all_recipes
from hevi.production.p5_3.retrieval import (
    EVIDENCE_MANDATORY,
    retrieve_recipes,
    retrieve_with_evidence,
)
from hevi.production.p5_3.schema import RecipeSelectionEvidence


def _lib() -> RecipeLibrary:
    lib = RecipeLibrary()
    for r in load_all_recipes():
        lib.register(r)
    return lib


def _beat() -> VisualBeat:
    return VisualBeat(
        beat_id="b1", timeline_start_s=0.0, timeline_end_s=3.0,
        narration_span="test", intent_id="ESTABLISH_SUBJECT",
        shot_role="ESTABLISH", narrative_phase="HOOK",
    )


def test_evidence_mandatory_flag_is_true() -> None:
    assert EVIDENCE_MANDATORY is True


def test_retrieve_recipes_returns_evidence() -> None:
    lib = _lib()
    beat = _beat()
    result = retrieve_recipes(lib, beat)
    assert isinstance(result, tuple)
    assert len(result) == 2
    _candidates, evidence = result
    assert isinstance(evidence, RecipeSelectionEvidence)


def test_retrieve_recipes_evidence_has_selected_recipe() -> None:
    lib = _lib()
    beat = _beat()
    _, evidence = retrieve_recipes(lib, beat)
    assert evidence.selected_recipe_id
    assert evidence.selected_version == "1.0.0"


def test_retrieve_recipes_evidence_has_rejection_reasons() -> None:
    lib = _lib()
    beat = _beat()
    _, evidence = retrieve_recipes(lib, beat)
    assert evidence.rejected_candidates
    assert set(evidence.rejected_candidates) == set(evidence.rejection_reasons)


def test_retrieve_recipes_evidence_is_deterministic() -> None:
    lib = _lib()
    beat = _beat()
    _, e1 = retrieve_recipes(lib, beat)
    _, e2 = retrieve_recipes(lib, beat)
    assert e1.selected_recipe_id == e2.selected_recipe_id
    assert e1.candidate_recipe_ids == e2.candidate_recipe_ids
    assert e1.rejection_reasons == e2.rejection_reasons


def test_retrieve_recipes_matches_retrieve_with_evidence() -> None:
    lib = _lib()
    beat = _beat()
    cands_a, ev_a = retrieve_recipes(lib, beat)
    cands_b, ev_b = retrieve_with_evidence(lib, beat)
    assert [c.recipe_id for c in cands_a] == [c.recipe_id for c in cands_b]
    assert ev_a.selected_recipe_id == ev_b.selected_recipe_id
    assert ev_a.candidate_recipe_ids == ev_b.candidate_recipe_ids


def test_no_evidence_free_path() -> None:
    """There is no way to call retrieve_recipes without getting evidence."""
    lib = _lib()
    beat = _beat()
    result = retrieve_recipes(lib, beat, profile_id="EMOTIONAL_BOOK_REVIEW")
    assert isinstance(result, tuple)
    _, evidence = result
    assert isinstance(evidence, RecipeSelectionEvidence)
    assert evidence.selected_recipe_id
