"""assembly.beat_align 能力化测试 — 注册可见性 + 纯函数 + 离线 render。

不调 librosa 真检测 (monkeypatch detect_beat_times),不走付费链,纯离线。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import hevi.capabilities  # noqa: F401  (import registers bundled capabilities)
from hevi.capabilities import contains, get
from hevi.capabilities.beat_align import compute_beat_alignment
from hevi.capabilities.errors import CapabilityError


def test_beat_align_capability_is_registered():
    assert contains("assembly.beat_align")
    cap = get("assembly.beat_align")
    assert cap.name == "assembly.beat_align"
    assert cap.line == "assembly"
    assert "audio_path" in cap.params_schema["properties"]
    assert cap.params_schema["required"] == ["audio_path"]


def test_compute_beat_alignment_per_seam():
    out = compute_beat_alignment(
        beats=[4.7, 9.6], durations=[5.0, 5.0, 5.0], base_xfade_d=0.5, max_shift=0.3
    )
    assert out["fallback"] is False
    assert out["beat_count"] == 2
    assert len(out["snapped_durations"]) == 2
    assert out["snapped_durations"][0] == pytest.approx(0.8, abs=0.01)
    assert out["snapped_durations"][1] == pytest.approx(0.2, abs=0.01)


def test_compute_beat_alignment_no_beats_is_fallback_uniform():
    out = compute_beat_alignment(beats=[], durations=[5.0, 5.0, 5.0], base_xfade_d=0.5)
    assert out["fallback"] is True
    assert out["beats"] == []
    assert out["snapped_durations"] == [0.5, 0.5]


def test_compute_beat_alignment_no_durations_returns_beats_only():
    out = compute_beat_alignment(beats=[1.0, 1.5], durations=None)
    assert out["beats"] == [1.0, 1.5]
    assert out["snapped_durations"] == []
    assert out["fallback"] is False


def test_beat_align_render_missing_file_raises(tmp_path: Path):
    cap = get("assembly.beat_align")
    with pytest.raises(CapabilityError, match="not found"):
        cap.render_safe(
            {"audio_path": str(tmp_path / "nope.wav"), "durations": [5.0, 5.0]},
            tmp_path / "out",
        )


def test_beat_align_render_with_beats(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "hevi.assembly.beat_align.detect_beat_times", lambda p: [4.7, 9.6]
    )
    audio = tmp_path / "bgm.wav"
    audio.write_bytes(b"fake-audio-bytes")
    cap = get("assembly.beat_align")
    result = cap.render_safe(
        {"audio_path": str(audio), "durations": [5.0, 5.0, 5.0], "base_xfade_d": 0.5},
        tmp_path / "out",
    )
    assert result.qa["fallback"] is False
    assert result.qa["beat_count"] == 2
    assert result.qa["snapped_durations"][0] == pytest.approx(0.8, abs=0.01)
    assert result.qa["snapped_durations"][1] == pytest.approx(0.2, abs=0.01)
    report = json.loads(Path(result.qa["report"]).read_text(encoding="utf-8"))
    assert report["beats"] == [4.7, 9.6]
    assert len(report["snapped_durations"]) == 2


def test_beat_align_render_no_beats_falls_back_not_fake_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("hevi.assembly.beat_align.detect_beat_times", lambda p: [])
    audio = tmp_path / "bgm.wav"
    audio.write_bytes(b"fake-audio-bytes")
    cap = get("assembly.beat_align")
    result = cap.render_safe(
        {"audio_path": str(audio), "durations": [5.0, 5.0, 5.0], "base_xfade_d": 0.5},
        tmp_path / "out",
    )
    # No beats is honest fallback, explicitly flagged -- not a fake snap.
    assert result.qa["fallback"] is True
    assert result.qa["beats"] == []
    assert result.qa["snapped_durations"] == [0.5, 0.5]
