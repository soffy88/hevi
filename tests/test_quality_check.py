"""hevi.video.quality_check 测试 — 纯函数 + lavfi 真 ffmpeg 体检。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from hevi.video.quality_check import (
    average_hash,
    consistency_score,
    hamming,
    probe_stats,
    quality_report,
)

_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
ffmpeg_only = pytest.mark.skipif(not _HAS_FFMPEG, reason="needs ffmpeg")


def test_hamming() -> None:
    assert hamming("ff", "ff") == 0
    assert hamming("ff", "00") == 8
    assert hamming("0f", "00") == 4


def test_consistency_score_identical() -> None:
    # 完全相同的帧 → 连续性满分
    assert consistency_score([" abc123"[1:], "abc123", "abc123"]) == 1.0
    assert consistency_score(["abc123", "abc123"]) == 1.0


def test_consistency_score_single() -> None:
    assert consistency_score(["abc123"]) == 1.0


def test_consistency_score_different() -> None:
    # 全 0 与全 f 交替 → 连续性低
    score = consistency_score(["0000000000000000", "ffffffffffffffff"])
    assert score == pytest.approx(0.0, abs=0.01)


def test_average_hash_shape() -> None:
    from PIL import Image

    h = average_hash(Image.new("RGB", (100, 100), (128, 128, 128)))
    assert len(h) == 16  # 8x8=64 bit = 16 hex chars


@ffmpeg_only
def test_probe_stats(tmp_path: Path) -> None:
    clip = tmp_path / "c.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=3:size=640x480:rate=24",
         "-pix_fmt", "yuv420p", str(clip)],
        check=True, capture_output=True,
    )
    s = probe_stats(clip)
    assert s.duration == pytest.approx(3.0, abs=0.3)
    assert (s.width, s.height) == (640, 480)
    assert s.fps == pytest.approx(24.0, abs=0.5)
    assert not s.has_audio


@ffmpeg_only
async def test_quality_report_duration_violation(tmp_path: Path) -> None:
    clip = tmp_path / "c.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=24",
         "-pix_fmt", "yuv420p", str(clip)],
        check=True, capture_output=True,
    )
    # 预期 10s 但实际 3s → 违例
    rep = await quality_report(clip, expected_duration=10.0, n_samples=4)
    assert not rep.passed
    assert any("时长" in v for v in rep.violations)
    # 静态 testsrc 各帧相似 → 连续性较高
    assert rep.consistency > 0.5


@ffmpeg_only
async def test_quality_report_pass(tmp_path: Path) -> None:
    clip = tmp_path / "c.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=4:size=320x240:rate=24",
         "-pix_fmt", "yuv420p", str(clip)],
        check=True, capture_output=True,
    )
    rep = await quality_report(
        clip, expected_duration=4.0, expected_resolution=(320, 240),
        duration_tol=0.5, n_samples=4,
    )
    assert rep.passed, rep.violations
    assert len(rep.phashes) == 4
