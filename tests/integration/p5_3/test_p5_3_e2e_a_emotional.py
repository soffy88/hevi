"""E2E-A — real EMOTIONAL_BOOK_REVIEW: >=6 VisualBeats, >=4 recipe families."""

from __future__ import annotations

from pathlib import Path

import pytest
from p5_3_e2e_helpers import make_beats, make_library, probe_duration, render_video

from hevi.production.creative_ledger import CreativeLedger
from hevi.production.p5_3.creative_integration import record_recipe_usage
from hevi.production.p5_3.retrieval import retrieve_recipes
from hevi.production.p5_3.schema import RecipeUsageRecord

pytestmark = pytest.mark.slow


def test_e2e_a_emotional_book_review(tmp_path: Path) -> None:
    lib = make_library()
    beats = make_beats(6, profile="EMOTIONAL_BOOK_REVIEW", intent="EVOKE_EMOTION")
    ledger = CreativeLedger()

    families_seen: set[str] = set()
    for beat in beats:
        cands = retrieve_recipes(lib, beat, profile_id="EMOTIONAL_BOOK_REVIEW")
        assert cands, f"no candidates for {beat.beat_id}"
        selected = cands[0]
        for c in cands:
            recipe = lib.get_version(c.recipe_id, c.version)
            families_seen.add(recipe.recipe_family.value)
        record_recipe_usage(ledger, RecipeUsageRecord(
            recipe_id=selected.recipe_id, recipe_version=selected.version,
            profile="EMOTIONAL_BOOK_REVIEW", content_id="e2e-a",
            beat_role=beat.shot_role,
        ))

    assert len(beats) >= 6
    assert len(families_seen) >= 4, f"only {len(families_seen)} families: {families_seen}"

    video = render_video(beats, tmp_path / "render")
    assert video.is_file()
    assert probe_duration(video) > 0.0
    assert len(ledger.all_shots()) > 0
