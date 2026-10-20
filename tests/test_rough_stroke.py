"""Offline tests for the rough-style hand-drawn stroke technique.

Covers the clean-room technique module
(:mod:`hevi.layer4_legacy.handdraw.rough_stroke`), the registered
``image.rough_stroke`` capability, and the handdraw line's optional
``stroke_style="rough"`` switch (default ``legacy`` must be unchanged).
No network, no paid calls, CPU only.
"""
from __future__ import annotations

import hashlib
import random
from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.registry import CapabilityError
from hevi.layer4_legacy.handdraw.rough_stroke import (
    points_to_svg_path,
    roughen_polyline,
    roughen_polylines,
)

HOUSE = [(60.0, 220.0), (60.0, 120.0), (140.0, 60.0), (220.0, 120.0), (220.0, 220.0)]


# ---------------------------------------------------------------------------
# Technique module
# ---------------------------------------------------------------------------


def test_same_seed_same_output() -> None:
    a = roughen_polyline(HOUSE, roughness=2.0, bowing=2.0, seed=42)
    b = roughen_polyline(HOUSE, roughness=2.0, bowing=2.0, seed=42)
    assert a.passes == b.passes
    assert a.svg_paths == b.svg_paths
    other = roughen_polyline(HOUSE, roughness=2.0, bowing=2.0, seed=43)
    assert other.passes != a.passes


def test_module_does_not_touch_global_rng() -> None:
    random.seed(20261020)
    expected_next = random.random()
    random.seed(20261020)
    roughen_polyline(HOUSE, roughness=3.0, bowing=3.0, seed=7)
    roughen_polylines([HOUSE, HOUSE], roughness=3.0, bowing=3.0, seed=7)
    assert random.random() == expected_next


def test_zero_roughness_and_bowing_returns_original_path() -> None:
    result = roughen_polyline(HOUSE, roughness=0, bowing=0, seed=99)
    assert result.points == tuple(HOUSE)
    assert all(one_pass == tuple(HOUSE) for one_pass in result.passes)
    assert result.svg_path == points_to_svg_path(HOUSE)
    single = roughen_polyline(HOUSE, roughness=0, bowing=0, seed=99, double_stroke=False)
    assert len(single.passes) == 1


def test_double_stroke_gives_two_distinct_passes() -> None:
    result = roughen_polyline(HOUSE, roughness=2.0, bowing=1.0, seed=5)
    assert len(result.passes) == 2
    assert result.passes[0] != result.passes[1]
    # Each open pass holds the vertices plus one bowed midpoint per segment.
    assert len(result.passes[0]) == len(HOUSE) + (len(HOUSE) - 1)
    svg = result.svg_paths[0]
    assert svg.startswith("M ") and " L " in svg
    single = roughen_polyline(HOUSE, roughness=2.0, bowing=1.0, seed=5, double_stroke=False)
    assert len(single.passes) == 1
    assert single.passes[0] == result.passes[0]


def test_closed_polyline_wraps_and_svg_closes() -> None:
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    result = roughen_polyline(square, roughness=1.0, bowing=1.0, seed=3, closed=True)
    # 4 vertices + 4 bowed midpoints (incl. the wrap-around segment).
    assert len(result.passes[0]) == 8
    assert result.svg_path.endswith("Z")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"roughness": -0.1},
        {"roughness": 51},
        {"bowing": -1},
        {"bowing": float("inf")},
        {"roughness": "rough"},
        {"seed": 1.5},
        {"seed": True},
    ],
)
def test_invalid_params_raise(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        roughen_polyline(HOUSE, **kwargs)


@pytest.mark.parametrize(
    "points",
    [[], [(1.0, 2.0)], [(0.0, 0.0), (float("nan"), 1.0)], [(0.0, 0.0), ("x", 1.0)], None],
)
def test_invalid_points_raise(points) -> None:
    with pytest.raises(ValueError):
        roughen_polyline(points, roughness=1.0, bowing=1.0, seed=0)


# ---------------------------------------------------------------------------
# Capability registration
# ---------------------------------------------------------------------------


def test_rough_stroke_capability_is_registered() -> None:
    assert "image.rough_stroke" in caps.names()
    cap = caps.get("image.rough_stroke")
    assert cap.params_schema["additionalProperties"] is False


def test_rough_stroke_capability_rejects_invalid_params() -> None:
    cap = caps.get("image.rough_stroke")
    with pytest.raises(CapabilityError):
        cap.validate_params({})
    with pytest.raises(CapabilityError):
        cap.validate_params({"polylines": HOUSE, "roughness": -1})
    with pytest.raises(CapabilityError):
        cap.validate_params({"polylines": HOUSE, "unknown": 1})


def test_rough_stroke_capability_render_is_deterministic(tmp_path: Path) -> None:
    cap = caps.get("image.rough_stroke")
    params = {
        "polylines": [HOUSE],
        "roughness": 2.0,
        "bowing": 2.0,
        "double_stroke": True,
        "canvas_width": 280,
        "canvas_height": 280,
    }
    first = cap.render(params, tmp_path / "a", duration=0, aspect="1:1", seed=42)
    second = cap.render(params, tmp_path / "b", duration=0, aspect="1:1", seed=42)
    assert first.png and Path(first.png).is_file()
    assert first.sha256 == second.sha256
    assert hashlib.sha256(Path(first.png).read_bytes()).hexdigest() == first.sha256
    svg = Path(first.qa["svg"])
    assert svg.is_file() and "<path" in svg.read_text(encoding="utf-8")
    assert len(first.qa["svg_paths"]) == 2  # double stroke
    with pytest.raises(CapabilityError):
        cap.render({"polylines": [[(0.0, 0.0)]]}, tmp_path / "bad", duration=0, aspect="1:1", seed=1)


# ---------------------------------------------------------------------------
# Handdraw integration: default path unchanged, rough opt-in differs
# ---------------------------------------------------------------------------


def _illustration_sha(tmp_path: Path, name: str, **kwargs) -> str:
    from hevi.layer4_legacy.handdraw.illustrator import build_scene_illustration

    path = tmp_path / f"{name}.png"
    build_scene_illustration(
        scene_key="cat_courage", output_path=path, style_id="17", size=(240, 240), seed=7, **kwargs
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_handdraw_default_matches_explicit_legacy(tmp_path: Path) -> None:
    default_sha = _illustration_sha(tmp_path, "default")
    legacy_sha = _illustration_sha(tmp_path, "legacy", stroke_style="legacy")
    assert default_sha == legacy_sha


def test_handdraw_rough_switch_changes_output_and_is_deterministic(tmp_path: Path) -> None:
    legacy_sha = _illustration_sha(tmp_path, "legacy2", stroke_style="legacy")
    rough_a = _illustration_sha(tmp_path, "rough_a", stroke_style="rough")
    rough_b = _illustration_sha(tmp_path, "rough_b", stroke_style="rough")
    assert rough_a != legacy_sha
    assert rough_a == rough_b


def test_handdraw_rejects_unknown_stroke_style(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _illustration_sha(tmp_path, "bad_style", stroke_style="scribble")


def test_handdraw_illustration_capability_rough_opt_in(tmp_path: Path) -> None:
    cap = caps.get("handdraw.illustration")
    assert "stroke_style" in cap.params_schema["properties"]
    assert "rough" in cap.description
    base = {"topic": "小猫学新本领", "aspect": "16:9", "style_id": "17"}
    default = cap.render(base, tmp_path / "cap_default", duration=0, aspect="16:9", seed=11)
    rough = cap.render(
        {**base, "stroke_style": "rough"}, tmp_path / "cap_rough", duration=0, aspect="16:9", seed=11
    )
    assert default.qa["stroke_style"] == "legacy"
    assert rough.qa["stroke_style"] == "rough"
    assert default.sha256 != rough.sha256
    with pytest.raises(CapabilityError):
        cap.validate_params({**base, "stroke_style": "scribble"})
