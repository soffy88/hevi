"""E2E-C — real PRODUCT: PRODUCT_HERO, FEATURE_REVEAL, REAL_UI_FLOW."""

from __future__ import annotations

from pathlib import Path

import pytest
from p5_3_e2e_helpers import make_beats, make_library, probe_duration, render_video

from hevi.production.p5_3.schema import RecipeFamily

pytestmark = pytest.mark.slow


def test_e2e_c_product(tmp_path: Path) -> None:
    lib = make_library()
    beats = make_beats(4, profile="PRODUCT_HERO", intent="SHOW_PRODUCT")

    product_recipes = lib.search(family=RecipeFamily.PRODUCT)
    recipe_ids = {r.recipe_id for r in product_recipes}
    assert "PRODUCT.PRODUCT_HERO" in recipe_ids
    assert "PRODUCT.FEATURE_REVEAL" in recipe_ids
    assert "PRODUCT.REAL_UI_FLOW" in recipe_ids

    # Every product recipe must have constraints (no unsupported claims)
    for r in product_recipes:
        assert r.constraints or r.anti_patterns, f"{r.recipe_id} has no constraints"

    video = render_video(beats, tmp_path / "render")
    assert video.is_file()
    assert probe_duration(video) > 0.0
