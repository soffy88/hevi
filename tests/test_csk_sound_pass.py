"""Tests for the CSK sound pass (B2): cue collection, mix, mux, verify.

Unit-level tests use synthetic scaffold projects and a synthetic silent
MP4 (ffmpeg); no browser and no kit checkout are needed. The end-to-end
capability test in tests/test_csk_styles.py covers the real kit path.
"""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
import wave
from pathlib import Path

import pytest

from hevi.video.csk_styled_render import (
    CskError,
    _read_wav_envelope,
    collect_sound_cues,
    run_sound_pass,
)

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(not FFMPEG or not FFPROBE, reason="ffmpeg/ffprobe absent")


def _write_wav(path: Path, *, peak_at_s: float, duration_s: float = 0.4,
               rate: int = 48000) -> None:
    """Mono 16-bit WAV: silence except one full-scale sample at peak_at_s."""
    n = int(duration_s * rate)
    peak_frame = int(peak_at_s * rate)
    frames = bytearray()
    for i in range(n):
        frames += struct.pack("<h", 32767 if i == peak_frame else 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(bytes(frames))


def _scaffold_project(tmp_path: Path, *, cue_wavs: bool = True) -> Path:
    """Minimal scaffold-shaped project: index + one composition + cue wavs."""
    project = tmp_path / "project"
    (project / "compositions").mkdir(parents=True)
    (project / "csk" / "sfx").mkdir(parents=True)
    wav = project / "csk" / "sfx" / "hit.wav"
    if cue_wavs:
        _write_wav(wav, peak_at_s=0.05)
    audio_tag = (
        '<audio id="cue-1" src="csk/sfx/hit.wav" data-start="0.5" '
        'data-duration="0.4" data-track-index="20" data-volume="1.0" '
        'data-role="hit" data-peak="0.5" data-visual="appear" '
        'data-weight="hero"></audio>'
    )
    (project / "compositions" / "comp.html").write_text(
        f"<template><div>{audio_tag}</div></template>", encoding="utf-8"
    )
    (project / "index.html").write_text(
        '<div data-composition-id="c1" data-composition-src='
        '"compositions/comp.html" data-start="1.0" data-duration="2"></div>',
        encoding="utf-8",
    )
    return project


def test_collect_sound_cues_applies_host_offset(tmp_path: Path) -> None:
    project = _scaffold_project(tmp_path)
    cues = collect_sound_cues(project)
    assert len(cues) == 1
    # host data-start 1.0 + cue data-peak 0.5
    assert cues[0]["t"] == 1.5
    assert cues[0]["id"] == "cue-1"
    assert cues[0]["role"] == "hit"
    assert cues[0]["weight"] == "hero"
    assert Path(cues[0]["sound"]).is_file()


def test_collect_sound_cues_skips_tags_without_data_peak(tmp_path: Path) -> None:
    project = _scaffold_project(tmp_path)
    comp = project / "compositions" / "comp.html"
    comp.write_text(
        '<template><div><audio id="music" src="csk/sfx/hit.wav"></audio></div>'
        "</template>",
        encoding="utf-8",
    )
    assert collect_sound_cues(project) == []


def test_collect_sound_cues_empty_without_index(tmp_path: Path) -> None:
    assert collect_sound_cues(tmp_path / "nope") == []


def test_wav_envelope_peak_time(tmp_path: Path) -> None:
    wav = tmp_path / "peak.wav"
    _write_wav(wav, peak_at_s=0.25, duration_s=0.5)
    rate, envelope = _read_wav_envelope(wav)
    assert rate == 48000
    assert len(envelope) == 24000
    from hevi.video.csk_styled_render import _peak_time_in_window

    peak_t, amp = _peak_time_in_window(envelope, rate, 0.0, 0.5)
    assert peak_t == pytest.approx(0.25, abs=1 / rate)
    assert amp == pytest.approx(1.0, abs=1e-3)  # 32767/32768 full scale


def test_run_sound_pass_refuses_when_no_cues(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "index.html").write_text("<div></div>", encoding="utf-8")
    silent = tmp_path / "silent.mp4"
    silent.write_bytes(b"fake")
    with pytest.raises(CskError, match="no audio cues"):
        run_sound_pass(project, silent, tmp_path / "out.mp4", fps=4)


def test_run_sound_pass_refuses_when_cue_file_missing(tmp_path: Path) -> None:
    project = _scaffold_project(tmp_path, cue_wavs=False)
    silent = tmp_path / "silent.mp4"
    silent.write_bytes(b"fake")
    with pytest.raises(CskError, match="cue audio file"):
        run_sound_pass(project, silent, tmp_path / "out.mp4", fps=4)


@needs_ffmpeg
def test_run_sound_pass_mixes_muxes_and_measures_alignment(tmp_path: Path) -> None:
    project = _scaffold_project(tmp_path)
    silent = tmp_path / "silent.mp4"
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-f", "lavfi",
         "-i", "color=c=black:s=64x64:d=2", "-r", "4",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(silent)],
        check=True, capture_output=True,
    )
    out = tmp_path / "sounded.mp4"
    report = run_sound_pass(project, silent, out, fps=4)
    assert out.is_file() and out.stat().st_size > 1000
    assert report["status"] == "mixed"
    assert report["cue_count"] == 1
    # kit sound-layer QA is explicitly not run / not claimed.
    assert report["kit_sound_pass"] == "not_run"
    assert report["mixer"] == "hevi_ffmpeg_peak_aligned"
    cue = report["cues"][0]
    # cue at 1.5s, source peak at 0.05s -> delay 1450ms, measured peak ~1.5s.
    assert cue["delay_ms"] == 1450
    assert cue["alignment_error_s"] is not None
    assert abs(cue["alignment_error_s"]) <= 0.05
    assert abs(cue["alignment_error_frames"]) <= 1.0
    streams = {s["codec_type"] for s in report["streams"]}
    assert streams == {"video", "audio"}
    report_path = Path(report["report_json"])
    assert report_path.is_file()
    assert json.loads(report_path.read_text(encoding="utf-8"))["cue_count"] == 1
