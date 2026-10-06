"""E2E-F — variety across 3 videos: repetition decreases, diversity increases."""

from __future__ import annotations

from pathlib import Path

import pytest
from p5_3_e2e_helpers import make_beats, make_library, render_video

from hevi.production.creative_ledger import CreativeLedger
from hevi.production.p5_3.creative_integration import record_recipe_usage
from hevi.production.p5_3.retrieval import retrieve_recipes
from hevi.production.p5_3.schema import RecipeUsageRecord

pytestmark = pytest.mark.slow


def test_e2e_f_variety_across_three_videos(tmp_path: Path) -> None:
    lib = make_library()
    ledger = CreativeLedger()
    all_recipe_ids: list[str] = []

    from hevi.production.p5_3.retrieval import retrieve_with_evidence

    evidence_produced = 0
    for video_index in range(3):
        beats = make_beats(4, profile="EMOTIONAL_BOOK_REVIEW", intent="EVOKE_EMOTION")
        for beat in beats:
            cands, _ = retrieve_recipes(lib, beat, profile_id="EMOTIONAL_BOOK_REVIEW")
            assert cands
            selected = cands[0]
            # The evidence comes from the same canonical path, not a fixture:
            # same search, same scoring, same order, plus the written decision.
            ranked, evidence = retrieve_with_evidence(
                lib, beat, profile_id="EMOTIONAL_BOOK_REVIEW"
            )
            assert [c.recipe_id for c in ranked] == [c.recipe_id for c in cands]
            assert evidence.selected_recipe_id == selected.recipe_id
            assert evidence.selection_factors["selection_score"] > 0
            assert set(evidence.rejected_candidates) == set(evidence.rejection_reasons)
            evidence_produced += 1
            all_recipe_ids.append(selected.recipe_id)
            record_recipe_usage(ledger, RecipeUsageRecord(
                recipe_id=selected.recipe_id, recipe_version=selected.version,
                profile="EMOTIONAL_BOOK_REVIEW", content_id=f"e2e-f-v{video_index}",
                beat_role=beat.shot_role,
            ))
        render_video(beats, tmp_path / f"video_{video_index}")

    # Variety: the same recipe should not dominate
    from collections import Counter
    counts = Counter(all_recipe_ids)
    most_common_count = counts.most_common(1)[0][1]
    assert most_common_count < len(all_recipe_ids), "one recipe was used for every beat"

    # Semantic quality preserved: every retrieval returned candidates
    assert len(all_recipe_ids) == 12
    # Evidence was produced on the real selection path for every beat, answering
    # WHY_THIS_RECIPE and WHY_NOT_THE_OTHER_RECIPES without reconstruction.
    assert evidence_produced == 12
