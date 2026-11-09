"""S13: two-pass loudness normalisation (all lines)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from hevi.qa.loudness import measure_loudness, normalize_video_loudness


def _ffmpeg() -> str:
    binary = shutil.which("ffmpeg")
    if binary is None:
        pytest.skip("ffmpeg not installed")
    return binary


def _tone(path: Path) -> None:
    ffmpeg = _ffmpeg()
    wav = path.with_suffix(".wav")
    subprocess.run(
        [
            ffmpeg, "-y", "-v", "error", "-f", "lavfi",
            "-i", "sine=frequency=440:duration=2", "-af", "volume=0.08", str(wav),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            ffmpeg, "-y", "-v", "error",
            "-f", "lavfi", "-i", "color=c=black:s=160x284:r=10:d=2",
            "-i", str(wav), "-shortest",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", str(path),
        ],
        check=True,
        capture_output=True,
    )


def test_normalize_tone_to_minus_14(tmp_path: Path) -> None:
    _ffmpeg()
    video = tmp_path / "tone.mp4"
    _tone(video)
    before = measure_loudness(video)
    assert before["measured"] is True
    assert float(before["input_i"]) < -20

    evidence = normalize_video_loudness(video)
    assert evidence["normalized"] is True
    assert evidence["mode"] == "two-pass"
    after = measure_loudness(video)
    assert after["measured"] is True
    assert -15.2 <= float(after["input_i"]) <= -12.8
    assert float(after["input_tp"]) <= -1.0


def test_video_without_audio_is_left_alone(tmp_path: Path) -> None:
    ffmpeg = _ffmpeg()
    video = tmp_path / "silent.mp4"
    subprocess.run(
        [
            ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
            "color=c=black:s=160x284:r=10:d=1", "-c:v", "libx264",
            "-pix_fmt", "yuv420p", str(video),
        ],
        check=True,
        capture_output=True,
    )
    original = video.read_bytes()
    evidence = normalize_video_loudness(video)
    assert evidence["normalized"] is False
    assert "audio" in evidence["reason"]
    assert video.read_bytes() == original
