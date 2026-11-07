"""Tests for hevi.scene3d.generic (camera path, scene JSON, prompt gate, templates, render)."""
from __future__ import annotations

import json
import math
import struct
from pathlib import Path

import pytest

from hevi.scene3d.generic import (CatmullRom3, SceneError, bake_camera, check_prompt, expand_template,
                                  list_templates, normalize_scene)
from hevi.scene3d.generic.camera_path import frame_times, interp_keys
from hevi.scene3d.generic.html import build_html
from hevi.scene3d.generic.pipeline import prepare
from hevi.scene3d.generic.templates import LEGACY_ALIASES, load_template


def _dist(a, b):
    return math.dist(a, b)


def _mini(**kw):
    d = {"name": "t", "duration_s": 1, "fps": 8, "resolution": 64,
         "objects": [{"id": "box", "type": "box", "tags": ["盒子"]}],
         "camera": {"path": {"points": [[0, 1, 5], [3, 1, 3], [5, 1, 0]]}}}
    d.update(kw)
    return d


# ---------------- camera path (oskill) ---------------- #
@pytest.mark.parametrize("kind", ["centripetal", "catmullrom", "chordal"])
def test_curve_passes_through_endpoints_and_controls(kind):
    pts = [[0, 0, 0], [4, 1, 0], [6, 2, 5], [10, 0, 6]]
    c = CatmullRom3(pts, kind=kind)
    assert _dist(c.point_at(0), pts[0]) < 1e-6
    assert _dist(c.point_at(1), pts[-1]) < 1e-6
    for p in pts[1:-1]:  # interpolating spline: every control point lies on the curve
        assert min(_dist(c.point_at(i / 2000), p) for i in range(2001)) < 0.02


def test_curve_arc_length_even_speed_and_smooth():
    c = CatmullRom3([[0, 0, 0], [1, 0, 0], [10, 0, 3], [12, 0, 10]])
    steps = [_dist(c.point_at(i / 100), c.point_at((i + 1) / 100)) for i in range(100)]
    assert max(steps) / min(steps) < 1.15  # arc-length param -> near-constant speed
    assert abs(sum(steps) - c.length) / c.length < 0.01


def test_closed_curve_wraps():
    pts = [[10, 2, 0], [0, 2, 10], [-10, 2, 0], [0, 2, -10]]
    c = CatmullRom3(pts, closed=True)
    assert _dist(c.point_at(0), c.point_at(1.0 - 1e-9)) < 0.05
    assert _dist(c.point_at(0.25), c.point_at(1.25)) < 1e-9


def test_curve_rejects_bad_input():
    with pytest.raises(ValueError):
        CatmullRom3([[0, 0, 0]])
    with pytest.raises(ValueError):
        CatmullRom3([[0, 0], [1, 1]])


def test_lookat_is_slightly_ahead_on_curve():
    cam = {"fov": 45, "path": {"points": [[0, 0, 0], [5, 0, 0], [10, 0, 0]], "lookahead": 0.05}}
    fr = bake_camera(cam, 2.0, 10)
    for f in fr[:-1]:
        assert f["look"][0] > f["pos"][0]  # ahead along +x
        assert abs(f["look"][0] - f["pos"][0] - 0.5) < 0.05  # 5% of length 10
    assert fr[-1]["look"][0] > fr[-1]["pos"][0]  # extrapolated past the end, never looks at self


def test_look_at_target_blend():
    cam = {"path": {"points": [[0, 0, 0], [10, 0, 0]], "look_at": [0, 10, 0], "look_at_blend": 1.0}}
    assert all(f["look"] == [0, 10, 0] for f in bake_camera(cam, 1, 4))


def test_fov_roll_keyframes():
    keys = [{"t": 0, "fov": 40}, {"t": 2, "fov": 60}]
    assert interp_keys(keys, 1, "fov", 0) == pytest.approx(50)
    assert interp_keys(keys, -1, "fov", 0) == 40 and interp_keys(keys, 9, "fov", 0) == 60
    assert interp_keys([], 1, "fov", 33) == 33
    cam = {"fov": 45, "path": {"points": [[0, 0, 0], [1, 0, 0]]}, "fov_keys": keys,
           "roll_keys": [{"t": 0, "deg": 0}, {"t": 2, "deg": 20, "ease": "in_out"}]}
    fr = bake_camera(cam, 2, 4)
    assert fr[0]["fov"] == 40 and fr[-1]["fov"] == 60 and fr[-1]["roll_deg"] == 20
    assert 0 < fr[4]["roll_deg"] == pytest.approx(10)


def test_bake_is_deterministic_and_frame_count():
    cam = {"path": {"points": [[0, 0, 0], [3, 2, 1], [5, 0, 4]], "ease": "in_out"}}
    a, b = bake_camera(cam, 1.5, 24), bake_camera(cam, 1.5, 24)
    assert a == b and len(a) == 36 == len(frame_times(1.5, 24))
    assert frame_times(1.5, 24)[-1] == 1.5


# ---------------- scene JSON (oskill) ---------------- #
def test_normalize_defaults_and_size():
    s = normalize_scene(_mini())
    assert s["width"] == 114 and s["height"] == 64  # 16:9, even dims
    s2 = normalize_scene(_mini(camera={"aspect": "9:16", "path": {"points": [[0, 0, 1], [1, 0, 1]]}}))
    assert s2["width"] % 2 == 0 and s2["height"] > s2["width"]
    assert s["camera"]["path"]["curve"] == "centripetal" and s["fog"]["type"] == "none"


@pytest.mark.parametrize("bad", [
    {"objects": [{"type": "teapot"}]},
    {"objects": [{"type": "box", "material": {"color": "red"}}]},
    {"camera": {"path": {"points": [[0, 0, 0]]}}},
    {"lights": [{"type": "laser"}]},
    {"bogus": 1},
])
def test_schema_rejects(bad):
    with pytest.raises(SceneError):
        normalize_scene(_mini(**bad))


def test_duplicate_ids_and_closed_needs_three():
    with pytest.raises(SceneError):
        normalize_scene(_mini(objects=[{"id": "a", "type": "box"}, {"id": "g", "type": "group", "children": [{"id": "a", "type": "box"}]}]))
    with pytest.raises(SceneError):
        normalize_scene(_mini(camera={"path": {"points": [[0, 0, 0], [1, 0, 0]], "closed": True}}))


def test_gltf_must_be_local_existing(tmp_path):
    with pytest.raises(SceneError, match="local"):
        normalize_scene(_mini(objects=[{"type": "gltf", "src": "https://x/y.glb"}]))
    with pytest.raises(SceneError, match="not found"):
        normalize_scene(_mini(objects=[{"type": "gltf", "src": "nope.glb"}]), base_dir=tmp_path)
    g = _write_cube_glb(tmp_path / "cube.glb")
    s = normalize_scene(_mini(objects=[{"id": "c", "type": "gltf", "src": "cube.glb", "fit_height": 2}]), base_dir=tmp_path)
    assert s["objects"][0]["src"] == str(g.resolve())


# ---------------- prompt 3-part gate ---------------- #
def test_prompt_gate_pass_missing_forbidden():
    objs = [{"id": "boat", "type": "group", "tags": ["小船"], "children": [{"id": "tree1", "type": "cone", "tags": ["树"]}]}]
    ok = check_prompt({"prompt": {"subject": "s", "must_have": ["小船", "树"], "must_not": ["人物"]}, "objects": objs})
    assert ok["ok"] and not ok["missing"]
    with pytest.raises(SceneError, match="missing"):
        normalize_scene(_mini(prompt={"must_have": ["小船"]}))
    with pytest.raises(SceneError, match="forbidden"):
        normalize_scene(_mini(prompt={"must_not": ["盒子"]}))
    s = normalize_scene(_mini(prompt={"must_not": ["盒子"]}), enforce_prompt=False)
    assert s["prompt_report"]["forbidden_found"] == {"盒子": ["盒子"]}


# ---------------- templates ---------------- #
def test_templates_all_valid_and_legacy_aliases():
    names = list_templates()
    assert {"boat_sea_islands", "planet_orbit", "fox_wheat", "star_sea"} <= set(names)
    for n in names:
        s, cam = prepare({"template": n})
        assert s["prompt_report"]["ok"], n
        assert len(cam) == math.ceil(s["duration_s"] * s["fps"])
    for legacy, tpl in LEGACY_ALIASES.items():
        assert load_template(legacy)["name"] == tpl


def test_template_override_deep_merge():
    d = expand_template({"template": "star_sea", "duration_s": 2, "camera": {"fov": 30}})
    assert d["duration_s"] == 2 and d["camera"]["fov"] == 30 and d["camera"]["path"]["points"]
    with pytest.raises(ValueError):
        expand_template({"template": "nope"})


def test_html_embeds_scene_and_camera():
    s, cam = prepare(_mini())
    h = build_html(s, cam)
    assert "__setFrame" in h and '"box"' in h and "/*SCENE*/" not in h and "Math.random" not in h and "Date.now" not in h


# ---------------- capability ---------------- #
def test_capability_registered():
    import hevi.capabilities as caps
    import hevi.capabilities.scene3d_generic  # noqa: F401
    c = caps.get("scene3d.generic")
    assert c.supports_aspect("1:1")
    with pytest.raises(Exception):
        c.validate_params({"bogus": 1})


# ---------------- real render (CPU / SwiftShader) ---------------- #
def _chromium():
    try:
        from hevi.layer4_legacy.scene3d.browser import chromium_available
        return chromium_available()
    except Exception:
        return False


needs_browser = pytest.mark.skipif(not _chromium(), reason="no chromium bundle")


def _write_cube_glb(path: Path) -> Path:
    pos = [-.5, -.5, .5, .5, -.5, .5, .5, .5, .5, -.5, .5, .5, -.5, -.5, -.5, .5, -.5, -.5, .5, .5, -.5, -.5, .5, -.5]
    idx = [0, 1, 2, 0, 2, 3, 1, 5, 6, 1, 6, 2, 5, 4, 7, 5, 7, 6, 4, 0, 3, 4, 3, 7, 3, 2, 6, 3, 6, 7, 4, 5, 1, 4, 1, 0]
    pb, ib = struct.pack(f"<{len(pos)}f", *pos), struct.pack(f"<{len(idx)}H", *idx)
    binc = pb + ib + b"\0" * ((4 - len(pb + ib) % 4) % 4)
    gltf = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0}]}],
            "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [1, 0.2, 0.2, 1]}}],
            "buffers": [{"byteLength": len(binc)}],
            "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(pb)}, {"buffer": 0, "byteOffset": len(pb), "byteLength": len(ib)}],
            "accessors": [{"bufferView": 0, "componentType": 5126, "count": 8, "type": "VEC3", "min": [-.5] * 3, "max": [.5] * 3},
                          {"bufferView": 1, "componentType": 5123, "count": len(idx), "type": "SCALAR"}]}
    js = json.dumps(gltf).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    body = struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(binc), 0x004E4942) + binc
    path.write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body)
    return path


@needs_browser
def test_render_deterministic_with_gltf(tmp_path):
    from hevi.scene3d.generic import render_scene
    _write_cube_glb(tmp_path / "cube.glb")
    doc = _mini(duration_s=0.5, fps=8, objects=[
        {"id": "cube", "type": "gltf", "src": "cube.glb", "fit_height": 1.5, "tags": ["方块"], "anim": {"spin": {"speed_deg": 90}}},
        {"id": "sea", "type": "water", "params": {"size": 20, "segments": 16}},
        {"id": "stars", "type": "points", "params": {"count": 200, "radius": 30}}],
        prompt={"subject": "方块", "must_have": ["方块"], "must_not": ["人物"]},
        fog={"type": "linear", "color": "#aaccee", "near": 5, "far": 30},
        background={"type": "gradient", "top": "#112233", "bottom": "#445566"})
    a = render_scene(doc, tmp_path / "a", base_dir=tmp_path, sheet=False)
    b = render_scene(doc, tmp_path / "b", base_dir=tmp_path, sheet=False)
    assert a["frame_count"] == a["nb_read_frames"] == 4
    assert a["frames_sha256"] == b["frames_sha256"]  # byte-identical frames
    assert (a["width"], a["height"]) == (114, 64)


@needs_browser
def test_render_fails_loudly_on_bad_gltf(tmp_path):
    from hevi.scene3d.generic import render_scene
    (tmp_path / "bad.glb").write_bytes(b"not a glb")
    with pytest.raises(Exception, match="gltf|scene page error"):
        render_scene(_mini(duration_s=0.25, objects=[{"type": "gltf", "src": "bad.glb"}]), tmp_path / "o", base_dir=tmp_path, sheet=False)
