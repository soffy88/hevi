"""Round 3h(3GS G2/G3 道具路径)测试: prop3d / scene_block_workflow / 注册。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hevi.assembly.scene_block_workflow import (
    DEFAULT_AZIMUTHS,
    SceneBlockConfig,
    SceneBlockInput,
    scene_block_workflow,
)
from hevi.director.prop3d import (
    Prop3DError,
    PropBlueprint,
    blueprint_to_threejs,
    build_harness,
    build_prop_blueprint,
    camera_position,
    lint_blueprint,
)
from hevi.director.scene_contract import screen_direction


def _png(path: Path, color: tuple[int, int, int] = (120, 90, 60)) -> Path:
    from PIL import Image

    Image.new("RGB", (32, 32), color).save(path)
    return path


def _good_blueprint() -> dict[str, object]:
    return {
        "macro": {
            "description": "一把剑", "overall_shape": "composite",
            "proportions": "长条", "axis_aligned_size": [0.1, 1.0, 0.1],
        },
        "components": [
            {"name": "剑身", "primitive": "cube", "position": [0, 0.5, 0],
             "size": [0.05, 0.8, 0.02], "color": "#c0c0c0",
             "metalness": 0.9, "roughness": 0.2},
            {"name": "剑柄", "primitive": "cylinder", "position": [0, -0.2, 0],
             "size": [0.08, 0.3, 0.08], "color": "#4a2f1b",
             "metalness": 0.1, "roughness": 0.6},
        ],
        "topology": {"origin": [0, 0, 0], "orientation": "up=+Y"},
    }


# ---- 相机方位角数学(机位驱动渲染的几何核心)----

def test_camera_position_azimuths():
    # az=0 → 正对 +Z
    x, y, z = camera_position(0.0, distance=6.0, elevation_deg=18.0)
    assert abs(x) < 1e-3 and z > 0
    # az=90 → 右侧(+X)
    x, y, z = camera_position(90.0, distance=6.0, elevation_deg=18.0)
    assert x > 0 and abs(z) < 1e-3
    # az=-45 → 左侧
    x, y, z = camera_position(-45.0, distance=6.0, elevation_deg=18.0)
    assert x < 0 and z > 0
    # 俯拍 elevation>0 → y>0
    x, y, z = camera_position(0.0, distance=6.0, elevation_deg=45.0)
    assert y > 0


def test_camera_position_distance_scale():
    _x, _y, z = camera_position(0.0, distance=3.0, elevation_deg=0.0)
    assert abs(z - 3.0) < 1e-3


def test_screen_direction_from_azimuth():
    # 机位方位角 → 银幕方向(与 scene_contract 的消费衔接)
    assert screen_direction("", 0.0) == "front"
    assert screen_direction("", 45.0) == "right"
    assert screen_direction("", -45.0) == "left"
    assert screen_direction("", 180.0) == "back"


# ---- M.C.M.T 蓝图 ----

def test_lint_blueprint():
    assert lint_blueprint(_good_blueprint()) == []
    bad = _good_blueprint()
    bad["components"][0]["primitive"] = "icosahedron"  # type: ignore[attr-defined]
    assert any("primitive 非法" in i for i in lint_blueprint(bad))  # type: ignore[arg-type]
    empty = {"macro": {}, "components": []}
    assert lint_blueprint(empty)


def test_build_prop_blueprint_with_llm(tmp_path):
    img = _png(tmp_path / "sword.png")
    blueprint = build_prop_blueprint(
        img, llm=lambda **kw: json.dumps(_good_blueprint(), ensure_ascii=False)
    )
    assert isinstance(blueprint, PropBlueprint)
    assert len(blueprint.components) == 2


def test_build_prop_blueprint_no_llm(tmp_path):
    img = _png(tmp_path / "x.png")
    with pytest.raises(Prop3DError):
        build_prop_blueprint(img, llm=None)


def test_build_prop_blueprint_bad_json(tmp_path):
    img = _png(tmp_path / "x.png")
    with pytest.raises(Prop3DError):
        build_prop_blueprint(img, llm=lambda **kw: "not json")


def test_blueprint_to_threejs():
    bp = _good_blueprint()
    code = blueprint_to_threejs(
        PropBlueprint(
            macro=bp["macro"],
            components=bp["components"],
            topology=bp["topology"],
        )
    )
    assert "BoxGeometry" in code
    assert "CylinderGeometry" in code
    assert "MeshStandardMaterial" in code
    assert "parts.forEach" in code


# ---- HTML harness ----

def test_build_harness(tmp_path):
    code = blueprint_to_threejs(PropBlueprint(**_good_blueprint()))  # type: ignore[arg-type]
    harness = build_harness(code, azimuth_deg=45.0, out_path=tmp_path / "az45.html")
    html = harness.read_text(encoding="utf-8")
    assert "three.js" in html
    assert "camera.position.set" in html
    assert harness.exists()


# ---- scene_block_workflow ----

def test_scene_block_missing_llm(tmp_path):
    img = _png(tmp_path / "sword.png")
    res = __import__("asyncio").run(
        scene_block_workflow(
            SceneBlockConfig(out_dir=tmp_path, prop_name="sword"),
            SceneBlockInput(reference_image=img, llm=None),
            tmp_path,
        )
    )
    assert res["status"] == "failed"
    assert "LLM" in res["error"]


def test_scene_block_missing_reference(tmp_path):
    res = __import__("asyncio").run(
        scene_block_workflow(
            SceneBlockConfig(out_dir=tmp_path, prop_name="x"),
            SceneBlockInput(reference_image=tmp_path / "nope.png"),
            tmp_path,
        )
    )
    assert res["status"] == "failed"


def test_default_azimuths_include_back():
    assert DEFAULT_AZIMUTHS == (0.0, 45.0, -45.0, 180.0)


def test_scene_block_spatial_contract_logic(tmp_path):
    """LLM 注入后流程到"渲染"前全部可走(浏览器缺失时在 render 步降级 failed)。"""
    img = _png(tmp_path / "sword.png")

    def _fake_llm(**kw: object) -> str:
        return json.dumps(_good_blueprint(), ensure_ascii=False)

    res = __import__("asyncio").run(
        scene_block_workflow(
            SceneBlockConfig(out_dir=tmp_path, prop_name="sword", azimuths=(0.0, 45.0)),
            SceneBlockInput(reference_image=img, llm=_fake_llm),
            tmp_path,
        )
    )
    # 有 chromium 的宿主:整链渲染成功;缺失:render 步降级 failed(带 playwright 错误)。
    # 两种都是合法终态 —— 断言的是"flow 跑到了 render 步",而不是卡在 LLM/blueprint。
    assert res["status"] in ("completed", "failed")
    if res["status"] == "failed":
        assert "playwright" in res.get("error", "") or "chromium" in res.get("error", "").lower()
