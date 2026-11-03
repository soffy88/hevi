"""Tests for the ``video.manim_render`` capability (ManimCE).

Param-validation tests always run.  Render tests need the dedicated
Manim venv (``HEVI_MANIM_PYTHON`` or the default /data path) and are
skipped when it is absent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.capabilities import manim_render
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import get

MANIM_PY = manim_render.manim_python()
needs_manim = pytest.mark.skipif(
    not MANIM_PY.is_file(), reason=f"manim venv not installed at {MANIM_PY}"
)


def _render(params, out_dir):
    cap = get("video.manim_render")
    return cap.render(params, Path(out_dir), duration=0.0, aspect="16:9", seed=0)


def test_capability_registered():
    cap = get("video.manim_render")
    assert cap.name == "video.manim_render"
    assert cap.line == "explainer"


def test_missing_scene_name_rejected(tmp_path):
    with pytest.raises(CapabilityError):
        _render({"scene_code": "from manim import *\n"}, tmp_path)


def test_file_and_code_are_exclusive(tmp_path):
    with pytest.raises(CapabilityError):
        _render(
            {
                "scene_name": "X",
                "scene_file": "scene.py",
                "scene_code": "from manim import *\n",
            },
            tmp_path,
        )


def test_unknown_quality_rejected(tmp_path):
    with pytest.raises(CapabilityError):
        _render(
            {"scene_name": "X", "scene_code": "from manim import *\n", "quality": "ultra"},
            tmp_path,
        )


@needs_manim
def test_broken_scene_surfaces_real_error(tmp_path):
    with pytest.raises(CapabilityError) as excinfo:
        _render(
            {
                "scene_name": "Broken",
                "scene_code": "from manim import *\n\n\nclass Broken(Scene):\n"
                "    def construct(self):\n        raise RuntimeError('boom-marker')\n",
                "quality": "low",
            },
            tmp_path,
        )
    assert "boom-marker" in str(excinfo.value) or "Broken" in str(excinfo.value)


@needs_manim
def test_tiny_scene_render_smoke(tmp_path):
    result = _render(
        {
            "scene_name": "Tiny",
            "scene_code": "from manim import *\n\n\nclass Tiny(Scene):\n"
            "    def construct(self):\n"
            "        self.play(Create(Circle()), run_time=0.5)\n",
            "quality": "low",
        },
        tmp_path,
    )
    mp4 = Path(result.mp4)
    assert mp4.is_file() and mp4.stat().st_size > 0
    assert result.duration_s > 0
    assert result.qa["scene_name"] == "Tiny"
