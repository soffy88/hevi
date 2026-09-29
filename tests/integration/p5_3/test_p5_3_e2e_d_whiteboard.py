"""E2E-D — real WHITEBOARD: CONCEPT_BUILD, CAUSE_EFFECT, ANNOTATED_DIAGRAM."""

from __future__ import annotations

from pathlib import Path

import pytest
from p5_3_e2e_helpers import make_beats, make_library, probe_duration, render_video

from hevi.production.p5_3.schema import RecipeFamily

pytestmark = pytest.mark.slow


def test_e2e_d_whiteboard(tmp_path: Path) -> None:
    lib = make_library()
    beats = make_beats(5, profile="WHITEBOARD_EXPLAINER", intent="BUILD_UNDERSTANDING")

    explainer_recipes = lib.search(family=RecipeFamily.EXPLAINER)
    recipe_ids = {r.recipe_id for r in explainer_recipes}
    assert "EXPLAINER.CONCEPT_BUILD" in recipe_ids
    assert "EXPLAINER.CAUSE_EFFECT" in recipe_ids
    assert "EXPLAINER.ANNOTATED_DIAGRAM" in recipe_ids

    video = render_video(beats, tmp_path / "render")
    assert video.is_file()
    assert probe_duration(video) > 0.0
