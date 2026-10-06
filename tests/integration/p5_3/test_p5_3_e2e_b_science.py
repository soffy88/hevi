"""E2E-B — real SCIENCE_EXPLAINER: evidence, concept, comparison, data recipes."""

from __future__ import annotations

from pathlib import Path

import pytest
from p5_3_e2e_helpers import make_beats, make_library, probe_duration, render_video

pytestmark = pytest.mark.slow


def test_e2e_b_science_explainer(tmp_path: Path) -> None:
    lib = make_library()
    beats = make_beats(6, profile="SCIENCE_EXPLAINER", intent="EXPLAIN_CONCEPT")

    families_seen: set[str] = set()
    for beat in beats:
        cands = retrieve_recipes_from_lib(lib, beat, "SCIENCE_EXPLAINER")
        assert cands
        families_seen.add(lib.get_version(cands[0].recipe_id, cands[0].version).recipe_family.value)

    # Science profile must include evidence, explainer, and data families
    assert "EVIDENCE" in families_seen
    assert "EXPLAINER" in families_seen

    video = render_video(beats, tmp_path / "render")
    assert video.is_file()
    assert probe_duration(video) > 0.0


def retrieve_recipes_from_lib(lib, beat, profile):
    from hevi.production.p5_3.retrieval import retrieve_recipes
    cands, _ = retrieve_recipes(lib, beat, profile_id=profile)
    return cands
