"""audio.score_render 能力测试 — 注册可见性 + ABC 解析/拟合 + 离线 render。

纯 numpy 本地合成,不走付费链、不联网;渲染对象都是几小节的小乐谱,跑得快。
删除产物后断言失败的写法按契约惯例:产物在时 sha/可读断言成立,删掉后
compute_sha256 必须抛 CapabilityError、wave 打开必须失败。
"""
from __future__ import annotations

import hashlib
import json
import wave
from pathlib import Path

import pytest

import hevi.capabilities  # noqa: F401  (import registers bundled capabilities)
from hevi.capabilities import contains, get
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import compute_sha256
from hevi.capabilities.score_render import register_score_render_capabilities_once

register_score_render_capabilities_once()

SMALL_SCORE = """\
X:1
T:Two Marks
M:4/4
L:1/4
Q:1/4=120
K:C
V:1 inst=piano role=melody
V:2 inst=bass role=bass
V:1
!mark:intro! C D E F | !mark:chorus! G A B c | c2 z2 |
V:2
C,2 G,2 | C,2 G,2 | C,4 |
"""


def test_score_render_capability_is_registered():
    assert contains("audio.score_render")
    cap = get("audio.score_render")
    assert cap.name == "audio.score_render"
    assert cap.kind == "audio"
    props = cap.params_schema["properties"]
    for key in ("abc", "product", "scenes", "style", "align", "seed", "sample_rate"):
        assert key in props


def test_score_render_no_input_and_both_inputs_raise(tmp_path: Path):
    cap = get("audio.score_render")
    with pytest.raises(CapabilityError):
        cap.render_safe({}, tmp_path / "none")
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {
                "abc": SMALL_SCORE,
                "product": "devtool",
                "scenes": [{"id": "a", "start_s": 0.0, "end_s": 2.0}],
            },
            tmp_path / "both",
        )


def test_score_render_invalid_params_schema_raises(tmp_path: Path):
    cap = get("audio.score_render")
    with pytest.raises(CapabilityError):
        cap.render_safe({"abc": SMALL_SCORE, "sample_rate": "fast"}, tmp_path / "o")


def test_score_render_empty_score_raises(tmp_path: Path):
    cap = get("audio.score_render")
    # Header only, no notes at all.
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"abc": "X:1\nT:Empty\nM:4/4\nL:1/4\nK:C\n"}, tmp_path / "o1"
        )


def test_score_render_bad_header_raises(tmp_path: Path):
    cap = get("audio.score_render")
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"abc": "X:1\nT:Bad\nM:4/4\nL:1/4\nK:Zzz\nC D E F |\n"},
            tmp_path / "o2",
        )
    with pytest.raises(CapabilityError):
        cap.render_safe({"abc": "C D E F |\n"}, tmp_path / "o3")


def test_score_render_unknown_align_mark_raises(tmp_path: Path):
    cap = get("audio.score_render")
    with pytest.raises(CapabilityError, match="unknown mark"):
        cap.render_safe(
            {"abc": SMALL_SCORE, "align": {"nope": 1.0}}, tmp_path / "o"
        )


def test_score_render_non_increasing_align_raises(tmp_path: Path):
    cap = get("audio.score_render")
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"abc": SMALL_SCORE, "align": {"intro": 2.0, "chorus": 1.0}},
            tmp_path / "o",
        )


def test_score_render_marks_land_on_align(tmp_path: Path):
    cap = get("audio.score_render")
    out = tmp_path / "out"
    result = cap.render_safe(
        {"abc": SMALL_SCORE, "align": {"intro": 0.0, "chorus": 2.6}},
        out,
        seed=7,
    )
    sidecar = json.loads((out / "score_sidecar.json").read_text(encoding="utf-8"))
    marks = {m["name"]: m["at_s"] for m in sidecar["marks"]}
    assert marks["intro"] == pytest.approx(0.0, abs=0.03)
    assert marks["chorus"] == pytest.approx(2.6, abs=0.03)
    assert sidecar["engine"] == "numpy_synth"
    assert sidecar["seed"] == 7
    assert sidecar["note_count"] > 0
    assert len(sidecar["stretches"]) == 1
    stretch = sidecar["stretches"][0]
    assert stretch["from"] == "intro"
    assert stretch["to"] == "chorus"
    # nominal span is 4 beats at 120bpm = 2.0s -> fitted to 2.6s = +30% bend
    assert stretch["bend_pct"] == pytest.approx(30.0, abs=1.0)
    assert "rms_db" in stretch
    assert result.qa["marks"] == sidecar["marks"]
    assert result.wav == str(out / "score.wav")


def test_score_render_wav_is_readable(tmp_path: Path):
    cap = get("audio.score_render")
    out = tmp_path / "out"
    result = cap.render_safe({"abc": SMALL_SCORE}, out, seed=3)
    wav_path = Path(result.wav)
    assert wav_path.is_file()
    with wave.open(str(wav_path), "rb") as wf:
        assert wf.getnchannels() == 2
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 48000
        duration = wf.getnframes() / wf.getframerate()
    assert duration > 0
    assert result.duration_s == pytest.approx(duration, abs=0.05)
    assert result.sha256 == compute_sha256(wav_path)


def test_score_render_same_seed_reproducible_diff_seed_differs(tmp_path: Path):
    cap = get("audio.score_render")

    def _sha(out: Path, seed: int) -> str:
        result = cap.render_safe({"abc": SMALL_SCORE}, out, seed=seed)
        return hashlib.sha256(Path(result.wav).read_bytes()).hexdigest()

    a = _sha(tmp_path / "a", 11)
    b = _sha(tmp_path / "b", 11)
    c = _sha(tmp_path / "c", 12)
    assert a == b
    assert a != c


def test_score_render_direction_mode(tmp_path: Path):
    cap = get("audio.score_render")
    out = tmp_path / "out"
    result = cap.render_safe(
        {
            "product": "devtool",
            "scenes": [
                {"id": "hook", "start_s": 0.0, "end_s": 3.0, "energy": 0.5},
                {"id": "build", "start_s": 3.0, "end_s": 6.0, "energy": 0.7},
                {"id": "drop", "start_s": 6.0, "end_s": 9.0, "energy": 0.95},
            ],
        },
        out,
        seed=5,
    )
    assert Path(result.wav).is_file()
    gen = out / "generated_score.abc"
    assert gen.is_file()
    abc_text = gen.read_text(encoding="utf-8")
    assert "!mark:hook!" in abc_text
    assert "!mark:drop!" in abc_text
    assert "!hit!" in abc_text
    sidecar = json.loads((out / "score_sidecar.json").read_text(encoding="utf-8"))
    marks = {m["name"]: m["at_s"] for m in sidecar["marks"]}
    assert marks["hook"] == pytest.approx(0.0, abs=0.03)
    assert marks["build"] == pytest.approx(3.0, abs=0.03)
    assert marks["drop"] == pytest.approx(6.0, abs=0.03)
    with wave.open(str(result.wav), "rb") as wf:
        assert wf.getnframes() / wf.getframerate() > 0


def test_score_render_deleted_artifact_breaks_assertions(tmp_path: Path):
    cap = get("audio.score_render")
    out = tmp_path / "out"
    result = cap.render_safe({"abc": SMALL_SCORE}, out, seed=3)
    wav_path = Path(result.wav)
    assert wav_path.is_file()
    assert compute_sha256(wav_path) == result.sha256
    wav_path.unlink()
    assert not wav_path.exists()
    with pytest.raises(CapabilityError):
        compute_sha256(wav_path)
    with pytest.raises(OSError), wave.open(str(wav_path), "rb") as wf:
        wf.getnframes()
