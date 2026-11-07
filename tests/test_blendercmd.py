import json
import os

import pytest

from hevi.blendercmd import oskill_ops as K
from hevi.blendercmd.mcp_server import Server, TOOLS
from hevi.blendercmd.obase_runner import find_blender, run_ops, build_command
from hevi.blendercmd.omodul_session import BlenderSession

HAS_BL = find_blender() is not None
needs_bl = pytest.mark.skipif(not HAS_BL, reason="no blender")


def test_hex_to_rgb_linear():
    assert K.hex_to_rgb("#FFFFFF") == [1.0, 1.0, 1.0]
    assert K.hex_to_rgb("#000000") == [0.0, 0.0, 0.0]
    assert 0.2 < K.hex_to_rgb("#808080")[0] < 0.23
    with pytest.raises(K.OpError):
        K.hex_to_rgb("#12")


def test_validate_rejects_bad_ops():
    for bad in ({"op": "nope"}, {"op": "add", "type": "blob", "name": "x"}, {"op": "add", "type": "text", "name": "t"},
                {"op": "add", "type": "import", "name": "m", "path": "a.exe"}, {"op": "keyframe", "target": "a", "frame": 1},
                {"op": "add", "type": "cube", "name": "c", "location": [1, 2]}, {"op": "scene", "preset": "x"}):
        with pytest.raises(K.OpError):
            K.validate_op(bad)


def test_validate_normalises():
    o = K.validate_op({"op": "add", "type": "cube", "name": "c", "scale": 2})
    assert o["scale"] == [2.0, 2.0, 2.0]
    m = K.validate_op({"op": "material", "target": "c", "color": "#FF0000"})
    assert m["roughness"] == 0.9 and m["color"][0] == 1.0
    s = K.validate_op({"op": "scene", "preset": "cycles_fast"})
    assert K.validate_op({"op": "scene", "resolution": [427, 241]})["resolution"] == [428, 242]
    assert s["engine"] == "CYCLES" and s["denoise"] and s["samples"] == 8


def test_bounce_ops_valid_and_squash():
    ops = K.validate_ops(K.bounce_ball_ops(2.0, 24))
    kfs = [o for o in ops if o["op"] == "keyframe"]
    assert kfs[0]["frame"] == 1 and kfs[-1]["frame"] == 48
    contact = [k for k in kfs if k["scale"][2] < 1]
    assert contact and all(k["location"][2] < 0.5 for k in contact)
    assert max(k["location"][2] for k in kfs) == pytest.approx(2.5)


def test_build_command():
    c = build_command("/b/blender", "o.json", "r.json")
    assert c[:2] == ["/b/blender", "--background"] and c[-3:] == ["--", "o.json", "r.json"]


def test_session_persist_and_delete(tmp_path):
    s = BlenderSession(tmp_path)
    s.reset()
    s.add({"op": "add", "type": "cube", "name": "Box"})
    s.add({"op": "material", "target": "Box", "color": "#00FF00"})
    assert "Box" in BlenderSession(tmp_path).summary()["objects"]
    s.add({"op": "delete", "target": "Box"})
    assert not any(o.get("target") == "Box" or o.get("name") == "Box" for o in s.ops)
    with pytest.raises(ValueError):
        s.add({"op": "render_frame", "out": "x.png"})


def test_mcp_protocol(tmp_path):
    srv = Server(str(tmp_path))
    r = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}})
    assert r["result"]["serverInfo"]["name"] == "hevi-blender" and r["result"]["protocolVersion"] == "2025-03-26"
    assert srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    names = {t["name"] for t in srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
    assert {"blender_add_object", "blender_render_frame", "blender_keyframe", "blender_render_animation"} <= names
    r = srv.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "blender_add_object", "arguments": {"type": "sphere", "name": "B"}}})
    assert not r["result"]["isError"] and "B" in r["result"]["content"][0]["text"]
    r = srv.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                    "params": {"name": "blender_add_object", "arguments": {"type": "blob", "name": "B"}}})
    assert r["result"]["isError"]
    assert srv.handle({"jsonrpc": "2.0", "id": 5, "method": "bogus"})["error"]["code"] == -32601
    assert len(TOOLS) >= 10


@needs_bl
def test_real_render_frame_all_object_types(tmp_path):
    obj = tmp_path / "tri.obj"
    obj.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\nf 1 2 3\nf 1 2 4\nf 1 3 4\nf 2 3 4\n")
    ops = K.clay_base_ops("workbench", (160, 90), 24, 4) + [
        {"op": "add", "type": "sphere", "name": "S", "location": [-1.5, 0, 0.5], "radius": 0.5},
        {"op": "add", "type": "cube", "name": "C", "location": [0, 0, 0.4], "radius": 0.4},
        {"op": "add", "type": "cylinder", "name": "Y", "location": [1.5, 0, 0.5], "radius": 0.3},
        {"op": "add", "type": "text", "name": "T", "text": "hevi", "location": [0, 1, 1.5], "rotation": [90, 0, 0], "radius": 0.6},
        {"op": "add", "type": "import", "name": "M", "path": str(obj), "location": [0, -1, 0]},
        {"op": "material", "target": "M", "color": "#6FA8C9"},
        {"op": "keyframe", "target": "S", "frame": 1, "location": [-1.5, 0, 0.5]},
        {"op": "keyframe", "target": "S", "frame": 4, "location": [-1.5, 0, 2]},
        {"op": "render_frame", "frame": 4, "out": "f4.png"},
    ]
    r = run_ops(ops, str(tmp_path), timeout=300)
    assert r["ok"], r.get("error")
    png = r["outputs"][0]["path"]
    assert os.path.getsize(png) > 1000
    names = {o["name"] for o in r["objects"]}
    assert {"S", "C", "Y", "T", "M", "Ground", "Key", "Camera"} <= names
    s = next(o for o in r["objects"] if o["name"] == "S")
    assert s["location"][2] == pytest.approx(2.0, abs=1e-3)


@needs_bl
def test_real_error_reported(tmp_path):
    r = run_ops([{"op": "material", "target": "Ghost", "color": "#fff000"}], str(tmp_path), timeout=120)
    assert not r["ok"] and "Ghost" in r["error"]["message"]
