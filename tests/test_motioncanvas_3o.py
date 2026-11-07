"""Motion Canvas 3O 测试：oskill 纯函数单测 + （HEVI_MC_E2E=1）真实无头渲染。"""
import json
import os
import subprocess
from pathlib import Path

import pytest

from hevi.motioncanvas.oskill.script import ScriptError, project_meta, to_scene_tsx, total_duration, validate

SAMPLE = Path(__file__).resolve().parents[1] / "hevi/motioncanvas/data/sample_code_highlight.json"


def _mini(**kw):
    s = {"objects": [{"id": "c", "type": "code", "code": "a\nb\nc"}, {"id": "t", "type": "text", "text": "hi"},
                     {"id": "r", "type": "rect"}], "timeline": []}
    s.update(kw)
    return s


def test_sample_valid_and_5s():
    s = json.loads(SAMPLE.read_text(encoding="utf-8"))
    assert total_duration(s) == pytest.approx(5.0)
    tsx = to_scene_tsx(s)
    assert "lines(2, 4)" in tsx and "selection(DEFAULT" in tsx and "LezerHighlighter" in tsx


def test_ops_compile_in_order():
    tl = [{"op": "show", "target": "t"}, {"op": "highlight", "target": "c", "lines": 2, "duration": 0.2},
          {"op": "move", "target": "r", "x": 10, "y": -5, "scale": 2}, {"op": "wait", "duration": 1},
          {"op": "parallel", "steps": [{"op": "text", "target": "t", "text": "引号\"x", "duration": 0.5},
                                       {"op": "code", "target": "c", "code": "x\ny\nz\nw", "duration": 1.5}]},
          {"op": "highlight", "target": "c", "lines": [3, 4]}, {"op": "hide", "target": "t"}]
    s = _mini(timeline=tl)
    tsx = to_scene_tsx(s)
    body = [l.strip() for l in tsx.splitlines() if l.strip().startswith("yield*")]
    assert body[0] == "yield* t().opacity(1, 0.4);"
    assert body[1] == "yield* c().selection(lines(1, 1), 0.2);"
    assert body[2] == "yield* all(r().position([10, -5], 0.8), r().scale(2, 0.8));"
    assert body[3] == "yield* waitFor(1);"
    assert '\\"x' in body[4] and "all(" in body[4]
    assert body[5].startswith("yield* c().selection(lines(2, 3)")  # 第 4 行来自 code 步骤，允许
    assert total_duration(s) == pytest.approx(0.4 + 0.2 + 0.8 + 1 + 1.5 + 0.3 + 0.3)
    assert "Circle" not in tsx.split("\n")[1]


@pytest.mark.parametrize("bad", [
    _mini(timeline=[{"op": "fly", "target": "t"}]),
    _mini(timeline=[{"op": "show", "target": "nope"}]),
    _mini(timeline=[{"op": "highlight", "target": "c", "lines": 9}]),
    _mini(timeline=[{"op": "highlight", "target": "t", "lines": 1}]),
    _mini(timeline=[{"op": "move", "target": "r"}]),
    _mini(timeline=[{"op": "show", "target": "t", "duration": 0}]),
    _mini(timeline=[{"op": "parallel", "steps": []}]),
    _mini(objects=[{"id": "bad-id", "type": "text"}], timeline=[]),
    _mini(objects=[{"id": "x", "type": "video"}], timeline=[]),
    {"objects": []},
])
def test_validate_rejects(bad):
    with pytest.raises(ScriptError):
        validate(bad)


def test_meta_size_fps_no_audio():
    m = json.loads(project_meta(_mini(size=[640, 360], fps=24)))
    assert m["shared"]["size"] == {"x": 640, "y": 360}
    assert m["rendering"]["fps"] == 24 and m["rendering"]["exporter"]["options"]["includeAudio"] is False


def test_validate_does_not_mutate():
    s = _mini(timeline=[{"op": "show", "target": "t"}])
    validate(s)
    assert "duration" not in s["timeline"][0] and "size" not in s


@pytest.mark.skipif(os.environ.get("HEVI_MC_E2E") != "1", reason="真实渲染需 HEVI_MC_E2E=1（约 20s CPU）")
def test_e2e_render(tmp_path):
    from hevi.motioncanvas.omodul.render_script import render_script
    s = json.loads(SAMPLE.read_text(encoding="utf-8"))
    s["size"], s["fps"] = [320, 180], 12
    res = render_script(s, tmp_path / "o.mp4")
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height", "-of", "csv=p=0", res["mp4"]], capture_output=True, text=True).stdout
    assert out.strip() == "320,180"
    assert abs(res["duration"] - 5.0) < 0.3
