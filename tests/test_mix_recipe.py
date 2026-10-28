"""Tests for audio.mix_recipe: fixed numbers, runnable command, loudness."""

from __future__ import annotations

import math
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.mix_recipe import (
    build_ffmpeg_command,
    recipe,
    run_mix,
    verify_loudness,
)

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe required",
)


def _tone(path: Path, seconds: float, freq: float, amp: float = 0.2) -> Path:
    sr = 48000
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        for i in range(int(sr * seconds)):
            v = amp * math.sin(2.0 * math.pi * freq * i / sr)
            w.writeframes(int(v * 32767).to_bytes(2, "little", signed=True))
    return path


def _video(path: Path, seconds: int = 8) -> Path:
    proc = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"testsrc2=size=320x180:rate=10:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(path)],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    return path


def test_recipe_numbers_are_pinned() -> None:
    spec = recipe(-23.0)
    assert spec["target_lufs"] == -14.0
    assert spec["true_peak_ceiling_db"] == -1.0
    assert spec["voice_pre_norm_lufs"] == -16.0
    assert spec["ducking"] == {"threshold": 0.03, "ratio": 8, "attack": 20, "release": 300}
    assert spec["ducking_key"] == "voice" and spec["ducking_target"] == "bgm"
    assert spec["amix_normalize"] == 0
    assert spec["fade_sec"] == 1.0
    assert spec["video_codec"] == "copy"
    with pytest.raises(CapabilityError):
        recipe(-10.0)


def test_command_wiring(tmp_path: Path) -> None:
    voice = _tone(tmp_path / "voice.wav", 8.0, 440.0)
    bgm = _tone(tmp_path / "bgm.wav", 8.0, 220.0)
    video = _video(tmp_path / "film.mp4")
    cmd = build_ffmpeg_command(voice, bgm, video, tmp_path / "out.mp4", -23.0)
    joined = " ".join(cmd)
    assert "-c:v copy" in joined
    assert "sidechaincompress=threshold=0.03:ratio=8:attack=20:release=300" in joined
    assert "amix=inputs=2:normalize=0" in joined
    assert "afade=t=in" in joined and "afade=t=out" in joined
    # Voice is input 1, music input 2; the voice is split so one
    # branch feeds the mix and the other keys the compressor.
    assert "[voice]asplit=2[vmain][vsc]" in joined
    assert "[bgm][vsc]sidechaincompress" in joined


def test_run_mix_copies_video_and_measures_loudness(tmp_path: Path) -> None:
    voice = _tone(tmp_path / "voice.wav", 8.0, 440.0)
    bgm = _tone(tmp_path / "bgm.wav", 3.0, 220.0)  # shorter than film: must loop
    video = _video(tmp_path / "film.mp4")
    report = run_mix(voice, bgm, video, tmp_path / "mixed.mp4", -23.0)
    out = Path(report["output"])
    assert out.is_file()
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, timeout=60,
    )
    assert probe.stdout.strip() == "h264"
    gate = verify_loudness(out)
    assert gate["loudness"]["measured"] is True, gate
    assert gate["verdict"] == "pass", gate


def test_registry_mix(tmp_path: Path) -> None:
    voice = _tone(tmp_path / "voice.wav", 8.0, 440.0)
    bgm = _tone(tmp_path / "bgm.wav", 8.0, 220.0)
    video = _video(tmp_path / "film.mp4")
    cap = caps.get("audio.mix_recipe")
    result = cap.render_safe(
        {"voice_path": str(voice), "bgm_path": str(bgm), "video_path": str(video)},
        tmp_path / "out", duration=8.0, aspect="16:9", seed=1,
    )
    assert result.qa["loudness_gate"]["verdict"] == "pass"
