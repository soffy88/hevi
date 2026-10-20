"""image.watercolor_render 能力契约测试 — 注册/非法参数/确定性/参数影响。

纯离线、$0:只用 Pillow 小画布渲染,不走任何付费或网络链路。
核心断言:同 seed 同参数两次渲染 PNG 字节逐字节一致。
"""
from __future__ import annotations

import random
from pathlib import Path

import pytest

import hevi.capabilities  # noqa: F401  (import registers bundled capabilities)
from hevi.capabilities import contains, get
from hevi.capabilities.errors import CapabilityError
from hevi.watercolor import (
    demo_scene_shapes,
    displace_polygon,
    render_flat_image,
    render_watercolor_image,
)

NAME = "image.watercolor_render"
SMALL = {"width": 192, "height": 144, "layers": 12, "iterations": 3}


def _render(tmp_path: Path, sub: str, params: dict, seed: int = 42):
    cap = get(NAME)
    return cap.render_safe(params, tmp_path / sub, seed=seed)


def _preset_params(**over):
    params = {"scene_preset": "sun_mountain_lake", **SMALL}
    params.update(over)
    return params


def test_watercolor_capability_is_registered():
    assert contains(NAME)
    cap = get(NAME)
    assert cap.name == NAME
    assert cap.line == "watercolor"
    assert "shapes" in cap.params_schema["properties"]
    assert "layers" in cap.params_schema["properties"]
    assert "$0" in cap.description
    assert "Deterministic" in cap.description


@pytest.mark.parametrize(
    "bad",
    [
        {"scene_preset": "sun_mountain_lake", "layers": 0},
        {"scene_preset": "sun_mountain_lake", "layers": 201},
        {"scene_preset": "sun_mountain_lake", "alpha": 0},
        {"scene_preset": "sun_mountain_lake", "alpha": 1.5},
        {"scene_preset": "sun_mountain_lake", "iterations": 7},
        {"scene_preset": "sun_mountain_lake", "displacement": -1},
        {"scene_preset": "sun_mountain_lake", "width": 8},
        {"scene_preset": "atlantis"},
        {"shapes": [{"type": "blob", "color": "#FF0000"}]},
        {"shapes": [{"type": "circle", "color": "#FF0000"}], "bogus": 1},
    ],
)
def test_watercolor_invalid_params_raise(tmp_path: Path, bad: dict):
    params = {**SMALL, **bad}
    with pytest.raises(CapabilityError):
        _render(tmp_path, "bad", params)


def test_watercolor_missing_shapes_and_preset_raises(tmp_path: Path):
    with pytest.raises(CapabilityError, match="shapes or"):
        _render(tmp_path, "empty", dict(SMALL))


def test_watercolor_bad_shape_geometry_raises(tmp_path: Path):
    params = {
        **SMALL,
        "shapes": [
            {"type": "polygon", "points": [[0, 0], [10, 10]], "color": "#334455"}
        ],
    }
    with pytest.raises(CapabilityError):
        _render(tmp_path, "geo", params)


def test_same_seed_byte_identical(tmp_path: Path):
    params = _preset_params()
    r1 = _render(tmp_path, "a", params, seed=42)
    r2 = _render(tmp_path, "b", params, seed=42)
    b1 = Path(r1.png).read_bytes()
    b2 = Path(r2.png).read_bytes()
    assert b1 == b2  # core assertion: byte-for-byte reproducible
    assert r1.sha256 == r2.sha256
    assert Path(r1.png).is_file()


def test_different_seed_differs(tmp_path: Path):
    params = _preset_params()
    r1 = _render(tmp_path, "a", params, seed=42)
    r2 = _render(tmp_path, "b", params, seed=7)
    assert Path(r1.png).read_bytes() != Path(r2.png).read_bytes()


def test_layers_and_alpha_affect_output(tmp_path: Path):
    base = _render(tmp_path, "base", _preset_params(), seed=42)
    few = _render(tmp_path, "few", _preset_params(layers=3), seed=42)
    strong = _render(tmp_path, "strong", _preset_params(alpha=0.3), seed=42)
    base_bytes = Path(base.png).read_bytes()
    assert Path(few.png).read_bytes() != base_bytes
    assert Path(strong.png).read_bytes() != base_bytes


def test_core_render_deterministic_and_flat_differs():
    shapes = demo_scene_shapes(192, 144)
    a = render_watercolor_image(shapes, width=192, height=144, layers=12, iterations=3, seed=42)
    b = render_watercolor_image(shapes, width=192, height=144, layers=12, iterations=3, seed=42)
    assert a.tobytes() == b.tobytes()
    flat = render_flat_image(shapes, width=192, height=144)
    assert flat.tobytes() != a.tobytes()


def test_displace_polygon_deterministic_and_grows():
    pts = [(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)]
    p1 = displace_polygon(pts, random.Random(3), displacement=4.0, iterations=2)
    p2 = displace_polygon(pts, random.Random(3), displacement=4.0, iterations=2)
    assert p1 == p2
    assert len(p1) == len(pts) * 4
    assert p1 != pts


def test_deleted_artifact_fails_downstream_check(tmp_path: Path):
    result = _render(tmp_path, "gone", _preset_params())
    png = Path(result.png)
    assert png.is_file()
    png.unlink()
    assert not png.is_file()
    with pytest.raises(CapabilityError):
        from hevi.capabilities.registry import compute_sha256

        compute_sha256(png)
