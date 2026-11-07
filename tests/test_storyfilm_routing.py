"""Tests locking the storyfilm render routing (orphan-route fix).

The in-house film route is Ken Burns motion over shot stills
(``render_motion_film``). ``hyperframes`` is only its legacy alias; the
CSK styled renderer (``video.hyperframes_styled_render``) is a separate
capability and is not on this pipeline's path. These tests lock that
routing without running any paid stage (no LLM/TTS/image calls).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from hevi.storyfilm.pipeline import (
    RENDER_ROUTES,
    ROUTE_ALIASES,
    StoryFilmError,
    film_render_entry_for,
    resolve_render_route,
)


def test_route_table_is_exact() -> None:
    assert set(RENDER_ROUTES) == {"ken_burns", "pixstag_package"}
    assert ROUTE_ALIASES == {"hyperframes": "ken_burns"}
    assert RENDER_ROUTES["ken_burns"]["entry"] == (
        "hevi.storyfilm.pipeline.render_motion_film"
    )
    assert RENDER_ROUTES["ken_burns"]["produces"] == "film.mp4"
    assert RENDER_ROUTES["pixstag_package"]["entry"] == (
        "hevi.storyfilm.pipeline.build_pixstag_package"
    )


def test_hyperframes_alias_resolves_to_ken_burns() -> None:
    assert resolve_render_route("hyperframes") == "ken_burns"
    assert resolve_render_route("ken_burns") == "ken_burns"
    assert resolve_render_route("pixstag_package") == "pixstag_package"


def test_entry_for_alias_is_ken_burns_not_csk() -> None:
    entry = film_render_entry_for("hyperframes")
    assert entry["canonical_route"] == "ken_burns"
    assert entry["requested_route"] == "hyperframes"
    assert entry["entry"] == "hevi.storyfilm.pipeline.render_motion_film"
    assert "csk" not in entry["entry"]
    assert "hyperframes_styled_render" not in entry["entry"]


def test_unknown_and_csk_routes_rejected() -> None:
    for bad in ("", "csk", "csk_styled_render",
                "video.hyperframes_styled_render", "hyperframes_styled_render"):
        with pytest.raises(StoryFilmError, match="unknown render_route"):
            resolve_render_route(bad)


def test_pipeline_module_does_not_import_csk_renderer() -> None:
    """Fresh interpreter: importing the pipeline must not pull in CSK."""
    repo_root = Path(__file__).resolve().parents[1]
    code = (
        "import hevi.storyfilm.pipeline, sys; "
        "assert 'hevi.video.csk_styled_render' not in sys.modules, "
        "'pipeline imports the CSK renderer'; "
        "assert 'hevi.capabilities.csk_styles' not in sys.modules"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(repo_root), capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
