"""audio.music_analyze 能力测试 — 注册可见性 + 纯函数 + 真实 librosa 离线管线。

真实管线测试用合成音频 (已知真值): 120 BPM 点击轨 + 简单旋律, 22.05 kHz
单声道 wav, 时长 12 s。BPM 断言带容差: librosa 帧量化 (hop 512 @
22050 Hz ≈ 23 ms) 使逐拍间隔天然抖动, 本能力的最小二乘精修后应落在
120 ± 3 BPM 内; duration 与合成真值精确核对。whisper 对齐与 demucs
都不走真实模型: 对齐用 monkeypatch 替身, demucs 断言明确降级报错。
"""
from __future__ import annotations

import json
import math
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

import hevi.capabilities  # noqa: F401  (import registers bundled capabilities)
from hevi.audio.music_analyze import (
    MusicAnalyzeError,
    analyze_music,
    build_sections,
    downsample_envelope,
    estimate_downbeats,
    refine_bpm,
)
from hevi.capabilities import contains, get
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.music_analyze import register_music_analyze_capabilities_once

register_music_analyze_capabilities_once()

TRUE_BPM = 120.0
TRUE_DURATION_S = 12.0
SR = 22050


def _synth_120bpm(path: Path) -> Path:
    """120 BPM click track + quiet two-part melody (known ground truth)."""
    beat = 60.0 / TRUE_BPM
    n = int(SR * TRUE_DURATION_S)
    y = np.zeros(n, dtype=np.float64)
    for i, bt in enumerate(np.arange(0.0, TRUE_DURATION_S, beat)):
        idx = int(bt * SR)
        length = int(0.05 * SR)
        tt = np.arange(length) / SR
        freq = 2000.0 if i % 4 == 0 else 1500.0
        amp = 0.8 if i % 4 == 0 else 0.55
        y[idx : idx + length] += amp * np.sin(2 * np.pi * freq * tt) * np.exp(-tt * 60)
    notes_a = [261.63, 329.63, 392.0, 523.25]
    notes_b = [220.0, 261.63, 329.63, 440.0]
    for beat_i in range(int(TRUE_DURATION_S / beat)):
        bt = beat_i * beat
        idx = int(bt * SR)
        length = int(beat * SR * 0.85)
        tt = np.arange(length) / SR
        f = (notes_a if bt < TRUE_DURATION_S / 2 else notes_b)[beat_i % 4]
        env = 0.12 * (1 - np.exp(-tt * 40)) * np.exp(-tt * 3.0)
        y[idx : idx + length] += env * np.sin(2 * np.pi * f * tt)
    sf.write(str(path), np.clip(y, -0.98, 0.98).astype(np.float32), SR)
    return path


# ---------------------------------------------------------------- registry


def test_music_analyze_capability_is_registered():
    assert contains("audio.music_analyze")
    cap = get("audio.music_analyze")
    assert cap.name == "audio.music_analyze"
    assert cap.kind == "audio"
    assert cap.line == "audio"
    props = cap.params_schema["properties"]
    for key in (
        "audio_path",
        "lyrics",
        "language",
        "beats_per_bar",
        "include_stems",
        "loudness_max_points",
    ):
        assert key in props
    assert cap.params_schema["required"] == ["audio_path"]
    # The downgrade / single-path honesty must be visible in the catalogue.
    assert "Demucs" in cap.description
    assert "CTC" in cap.description


# ---------------------------------------------------------------- pure core


def test_refine_bpm_least_squares_beats_quantised_intervals():
    # Intervals alternating 0.4876/0.5107 (hop quantisation): the fit must
    # land near the true 0.5 s interval, not on either quantised value.
    beats = [0.0]
    for i in range(20):
        beats.append(beats[-1] + (0.4876 if i % 2 == 0 else 0.5107))
    assert refine_bpm(beats, 117.45) == pytest.approx(120.0, abs=1.0)


def test_refine_bpm_fallbacks():
    assert refine_bpm([], 98.7654) == pytest.approx(98.765)
    assert refine_bpm([1.0], 98.0) == pytest.approx(98.0)
    assert refine_bpm([0.0, 0.5], 98.0) == pytest.approx(120.0)


def test_estimate_downbeats_phase_voted_by_strength():
    beats = [0.5 * i for i in range(8)]
    strengths = [10.0, 1.0, 1.0, 1.0, 10.0, 1.0, 1.0, 1.0]
    assert estimate_downbeats(beats, strengths, beats_per_bar=4) == [0.0, 2.0]
    # Phase shifted: strong beats at indices 1 and 5.
    strengths2 = [1.0, 10.0, 1.0, 1.0, 1.0, 10.0, 1.0, 1.0]
    assert estimate_downbeats(beats, strengths2, beats_per_bar=4) == [0.5, 2.5]
    assert estimate_downbeats([], None) == []


def test_build_sections_tiles_duration():
    sections = build_sections([9.0, 3.0, 3.0, -1.0, 12.0], 12.0)
    assert [(s["start_s"], s["end_s"]) for s in sections] == [
        (0.0, 3.0),
        (3.0, 9.0),
        (9.0, 12.0),
    ]
    assert build_sections([], 5.0) == [
        {"index": 0, "start_s": 0.0, "end_s": 5.0, "duration_s": 5.0}
    ]
    with pytest.raises(MusicAnalyzeError):
        build_sections([], 0.0)


def test_downsample_envelope_blocks_and_db():
    times = [i * 0.1 for i in range(100)]
    rms = [0.5] * 100
    env = downsample_envelope(times, rms, max_points=10)
    assert len(env["times_s"]) == 10
    assert env["rms"] == pytest.approx([0.5] * 10)
    assert env["db"] == pytest.approx([round(20 * math.log10(0.5), 2)] * 10)
    assert env["hop_s"] == pytest.approx(1.0, abs=0.01)
    small = downsample_envelope([0.0, 0.5], [0.0, 1.0], max_points=500)
    assert small["db"][0] == -80.0
    assert small["db"][1] == pytest.approx(0.0)


# ---------------------------------------------------------------- pipeline


def test_analyze_music_full_pipeline_known_truth(tmp_path: Path):
    audio = _synth_120bpm(tmp_path / "synth.wav")
    report = analyze_music(audio, loudness_max_points=200)

    # Structure: every field the contract promises is present.
    for key in (
        "duration_s",
        "sample_rate",
        "bpm",
        "tempo_raw",
        "beats",
        "beat_count",
        "downbeats",
        "downbeat_count",
        "onsets",
        "onset_count",
        "sections",
        "section_count",
        "loudness_envelope",
        "peak_db",
        "lyrics_alignment",
        "stems",
    ):
        assert key in report

    assert report["duration_s"] == pytest.approx(TRUE_DURATION_S, abs=0.05)
    assert report["sample_rate"] == SR
    assert report["bpm"] == pytest.approx(TRUE_BPM, abs=3.0)
    assert report["beat_count"] == len(report["beats"]) >= 15
    assert report["beats"] == sorted(report["beats"])
    assert report["downbeat_count"] == len(report["downbeats"]) >= 3
    assert set(report["downbeats"]) <= set(report["beats"])
    assert report["onset_count"] == len(report["onsets"]) >= 10
    # Sections tile the whole file exactly.
    sections = report["sections"]
    assert sections[0]["start_s"] == 0.0
    assert sections[-1]["end_s"] == pytest.approx(TRUE_DURATION_S, abs=0.05)
    for a, b in pairwise(sections):
        assert a["end_s"] == b["start_s"]
    env = report["loudness_envelope"]
    assert 0 < len(env["times_s"]) <= 200
    assert len(env["times_s"]) == len(env["rms"]) == len(env["db"])
    assert report["is_silent"] is False
    assert report["lyrics_alignment"] is None
    assert report["stems"] is None


def test_analyze_music_missing_file_raises(tmp_path: Path):
    with pytest.raises(MusicAnalyzeError, match="not found"):
        analyze_music(tmp_path / "nope.wav")


def test_analyze_music_include_stems_raises_demucs_downgrade(tmp_path: Path):
    audio = _synth_120bpm(tmp_path / "synth.wav")
    with pytest.raises(MusicAnalyzeError, match="demucs"):
        analyze_music(audio, include_stems=True)


def test_analyze_music_lyrics_alignment_uses_whisper_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    audio = _synth_120bpm(tmp_path / "synth.wav")
    fake_words = [
        {"text": "hello", "start_ms": 0, "end_ms": 400, "start_s": 0.0, "end_s": 0.4},
        {"text": "world", "start_ms": 500, "end_ms": 900, "start_s": 0.5, "end_s": 0.9},
    ]
    monkeypatch.setattr(
        "hevi.audio.music_analyze._align_lyrics_sync",
        lambda p, lyrics, language: fake_words,
    )
    report = analyze_music(audio, lyrics="hello world", language="en")
    alignment = report["lyrics_alignment"]
    assert alignment is not None
    assert alignment["source"] == "whisper_asr_local"
    assert alignment["cross_check"] is None  # single path, honestly labelled
    assert alignment["words"] == fake_words
    assert alignment["word_count"] == 2
    assert report["lyrics_alignment_error"] is None


def test_analyze_music_lyrics_alignment_failure_is_flagged_not_faked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    audio = _synth_120bpm(tmp_path / "synth.wav")

    def boom(p, lyrics, language):
        raise RuntimeError("whisper model unavailable")

    monkeypatch.setattr("hevi.audio.music_analyze._align_lyrics_sync", boom)
    report = analyze_music(audio, lyrics="hello world")
    assert report["lyrics_alignment"] is None
    assert "whisper model unavailable" in report["lyrics_alignment_error"]


# ---------------------------------------------------------------- render


def test_music_analyze_render_writes_report(tmp_path: Path):
    audio = _synth_120bpm(tmp_path / "synth.wav")
    cap = get("audio.music_analyze")
    result = cap.render_safe({"audio_path": str(audio)}, tmp_path / "out")
    assert result.duration_s == pytest.approx(TRUE_DURATION_S, abs=0.05)
    assert result.qa["bpm"] == pytest.approx(TRUE_BPM, abs=3.0)
    assert result.qa["beat_count"] >= 15
    assert result.qa["has_lyrics_alignment"] is False
    assert result.qa["stems"] == "unavailable_demucs_downgraded"
    report = json.loads(Path(result.qa["report"]).read_text(encoding="utf-8"))
    assert report["bpm"] == result.qa["bpm"]
    assert "loudness_envelope" in report
    assert report["sections"]


def test_music_analyze_render_missing_file_raises(tmp_path: Path):
    cap = get("audio.music_analyze")
    with pytest.raises(CapabilityError, match="not found"):
        cap.render_safe({"audio_path": str(tmp_path / "nope.wav")}, tmp_path / "out")


def test_music_analyze_render_include_stems_raises(tmp_path: Path):
    audio = _synth_120bpm(tmp_path / "synth.wav")
    cap = get("audio.music_analyze")
    with pytest.raises(CapabilityError, match="demucs"):
        cap.render_safe(
            {"audio_path": str(audio), "include_stems": True}, tmp_path / "out"
        )
