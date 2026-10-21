"""audio.score_render 采样音色路径测试 — vendored VCSL 采样库完整性、
采样渲染确定性（同 seed 字节一致）、采样与合成的差异、align 拟合在
采样路径上同样成立、未知乐器兜底合成 + sidecar 如实报告。

采样库是 CC0 数据（VCSL，经 mg-styles-15 整理，MIT），渲染纯本地
numpy + soundfile，不联网、不走付费链。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

import hevi.capabilities  # noqa: F401  (import registers bundled capabilities)
from hevi.audio import sampled
from hevi.audio.score_render import parse_abc, render_score
from hevi.capabilities import get
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.score_render import register_score_render_capabilities_once

register_score_render_capabilities_once()

SAMPLED_SCORE = """\
X:1
T:Sampled Marks
M:4/4
L:1/4
Q:1/4=120
K:C
V:1 inst=piano role=melody
V:2 inst=bass role=bass
V:1
!mark:intro! C D E F | !mark:chorus! G A B c |
V:2
C,2 G,2 | C,2 G,2 |
"""

MARIMBA_SCORE = """\
X:1
T:Marimba Voice
M:4/4
L:1/4
Q:1/4=120
K:C
V:1 inst=marimba role=melody
V:1
C D E G | A G E2 |
"""


def _rms(mix: np.ndarray) -> float:
    return float(np.sqrt(np.mean(mix**2)))


# ---------------------------------------------------------------- library


def test_sample_library_index_matches_files_on_disk():
    idx = json.loads(sampled.INDEX_PATH.read_text(encoding="utf-8"))
    assert idx["sample_count"] >= 100
    total_items = 0
    for meta in idx["instruments"].values():
        for item in meta["items"]:
            total_items += 1
            assert (sampled.SAMPLES_DIR / item["file"]).is_file(), item["file"]
            if meta["pitched"]:
                assert item["midi"] is not None
    assert total_items == idx["sample_count"]
    for name in ("piano", "marimba", "vibraphone", "harp", "glock", "kalimba"):
        assert name in idx["instruments"]
        assert idx["instruments"][name]["pitched"]


def test_sampled_note_is_deterministic_and_non_silent():
    a = sampled.render_sampled_note("piano", 60, 0.5, 90, 48000)
    b = sampled.render_sampled_note("piano", 60, 0.5, 90, 48000)
    assert np.array_equal(a, b)
    assert _rms(a.reshape(-1, 1)) > 0.001
    # a different pitch is a different (shifted) playback
    c = sampled.render_sampled_note("piano", 72, 0.5, 90, 48000)
    assert not np.array_equal(a, c)


def test_sampled_unknown_instrument_raises():
    with pytest.raises(sampled.SampledError):
        sampled.render_sampled_note("didgeridoo", 60, 0.5, 90, 48000)


# ------------------------------------------------------------- render_score


def test_render_sampled_deterministic_same_seed_and_differs_from_synth():
    score = parse_abc(SAMPLED_SCORE)
    mix_s, side_s = render_score(score, seed=11, timbre="sampled")
    mix_s2, _ = render_score(score, seed=11, timbre="sampled")
    assert np.array_equal(mix_s, mix_s2)  # byte-identical repeat render
    assert side_s["engine"] == "sampled"
    assert side_s["sampled"]["notes"] == side_s["note_count"]
    assert side_s["sampled"]["synth_fallback_notes"] == 0
    assert set(side_s["sampled"]["instruments"]) == {"piano"}
    assert _rms(mix_s) > 0.01  # mastered, non-silent

    mix_y, side_y = render_score(score, seed=11)  # default = synth
    assert side_y["engine"] == "numpy_synth"
    assert side_y["sampled"]["notes"] == 0
    assert mix_y.shape == mix_s.shape
    assert not np.array_equal(mix_y, mix_s)


def test_render_sampled_marks_still_land_on_align():
    score = parse_abc(SAMPLED_SCORE)
    _, side = render_score(
        score, {"intro": 0.0, "chorus": 2.6}, seed=7, timbre="sampled"
    )
    marks = {m["name"]: m["at_s"] for m in side["marks"]}
    assert marks["intro"] == pytest.approx(0.0, abs=0.03)
    assert marks["chorus"] == pytest.approx(2.6, abs=0.03)
    assert side["stretches"][0]["bend_pct"] == pytest.approx(30.0, abs=1.0)


def test_render_sampled_only_inst_name_selects_sampled():
    score = parse_abc(MARIMBA_SCORE)
    mix, side = render_score(score, seed=3)  # no timbre anywhere
    assert side["engine"] == "sampled"
    assert side["sampled"]["instruments"] == ["marimba"]
    assert side["voices"][0]["timbre"] == "sampled:marimba"
    assert _rms(mix) > 0.01


def test_render_unknown_sampled_inst_falls_back_to_synth_with_warning():
    score = parse_abc(
        MARIMBA_SCORE.replace("inst=marimba", "inst=piano timbre=sampled sampled_inst=nonsuch")
    )
    mix, side = render_score(score, seed=3)
    assert side["sampled"]["notes"] == 0
    assert side["sampled"]["synth_fallback_notes"] > 0
    assert any("using synth" in w for w in side["warnings"])
    assert _rms(mix) > 0.01


def test_render_bad_timbre_raises():
    score = parse_abc(SAMPLED_SCORE)
    with pytest.raises(ValueError):
        render_score(score, timbre="vinyl")


def test_render_sampled_drums_use_oneshots():
    score = parse_abc(
        """\
X:1
T:Drums
M:4/4
L:1/4
Q:1/4=120
K:C
V:1 inst=drums role=drums
V:1
C C C C | C C C C |
"""
    )
    mix, side = render_score(score, seed=5, timbre="sampled")
    assert side["sampled"]["notes"] > 0
    assert _rms(mix) > 0.005
    mix2, _ = render_score(score, seed=5, timbre="sampled")
    assert np.array_equal(mix, mix2)


# -------------------------------------------------------------- capability


def test_capability_timbre_param_end_to_end(tmp_path: Path):
    cap = get("audio.score_render")
    assert "timbre" in cap.params_schema["properties"]

    def _sha(out: Path, **kw) -> str:
        result = cap.render_safe({"abc": SAMPLED_SCORE, **kw}, out, seed=11)
        return hashlib.sha256(Path(result.wav).read_bytes()).hexdigest()

    a = _sha(tmp_path / "a", timbre="sampled")
    b = _sha(tmp_path / "b", timbre="sampled")
    c = _sha(tmp_path / "c")  # synth default
    assert a == b  # same seed + sampled -> identical wav bytes
    assert a != c
    sidecar = json.loads(
        (tmp_path / "a" / "score_sidecar.json").read_text(encoding="utf-8")
    )
    assert sidecar["engine"] == "sampled"
    assert sidecar["timbre"] == "sampled"
    assert sidecar["sampled"]["instruments"] == ["piano"]


def test_capability_bad_timbre_raises(tmp_path: Path):
    cap = get("audio.score_render")
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"abc": SAMPLED_SCORE, "timbre": "vinyl"}, tmp_path / "o"
        )
