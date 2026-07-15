"""hevi.video.quality_check 测试 — 纯函数 + lavfi 真 ffmpeg 体检。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from hevi.video.quality_check import (
    _parse_srt_windows,
    average_hash,
    consistency_score,
    hamming,
    measure_loudness,
    probe_stats,
    quality_report,
    subtitle_alignment_rate,
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
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=3:size=640x480:rate=24",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ],
        check=True,
        capture_output=True,
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
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=3:size=320x240:rate=24",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ],
        check=True,
        capture_output=True,
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
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=4:size=320x240:rate=24",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ],
        check=True,
        capture_output=True,
    )
    rep = await quality_report(
        clip,
        expected_duration=4.0,
        expected_resolution=(320, 240),
        duration_tol=0.5,
        n_samples=4,
    )
    assert rep.passed, rep.violations
    assert len(rep.phashes) == 4
    assert rep.loudness_lufs is None  # 无音轨 → 没测,不是 0
    assert rep.subtitle_alignment_rate is None  # 没传 subtitle_path → 没测


# Tier0 补全(HEVI 路线图 Phase1):响度 + 字幕对齐率。


def test_parse_srt_windows() -> None:
    srt = "1\n00:00:00,000 --> 00:00:02,500\nhello\n\n2\n00:00:03,000 --> 00:00:05,000\nworld\n"
    windows = _parse_srt_windows(srt)
    assert windows == [(0.0, 2.5), (3.0, 5.0)]


def test_parse_srt_windows_ignores_malformed_lines() -> None:
    assert _parse_srt_windows("not a timestamp line\n1\nhello") == []


@ffmpeg_only
def test_measure_loudness_on_silence(tmp_path: Path) -> None:
    clip = tmp_path / "silent.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono:d=2",
            "-c:a",
            "aac",
            str(clip),
        ],
        check=True,
        capture_output=True,
    )
    lufs = measure_loudness(clip)
    assert lufs is not None
    assert lufs < -45.0  # 真静音应远低于"几乎无声"的下限


def test_measure_loudness_missing_file_returns_none(tmp_path: Path) -> None:
    assert measure_loudness(tmp_path / "does_not_exist.mp4") is None


def test_subtitle_alignment_rate_missing_subtitle_file_returns_none(tmp_path: Path) -> None:
    assert subtitle_alignment_rate(tmp_path / "v.mp4", tmp_path / "missing.srt") is None


def test_subtitle_alignment_rate_empty_srt_returns_none(tmp_path: Path) -> None:
    srt = tmp_path / "empty.srt"
    srt.write_text("not a real subtitle file", encoding="utf-8")
    assert subtitle_alignment_rate(tmp_path / "v.mp4", srt) is None


def test_subtitle_alignment_rate_computes_overlap_fraction(tmp_path: Path) -> None:
    """mock ASR(同 test_subtitle_align.py 的既有惯例,不需要真跑 faster-whisper 模型):
    2 条字幕窗口,1 条跟 ASR 检测到的语音重叠,1 条完全对不上 → 对齐率 0.5。"""
    from hevi.assembly.subtitle_align import Cue

    srt = tmp_path / "s.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nhello\n\n2\n00:00:10,000 --> 00:00:12,000\nworld\n",
        encoding="utf-8",
    )
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")
    with patch(
        "hevi.assembly.subtitle_align.transcribe_to_cues",
        return_value=[Cue(start=0.1, end=1.9, text="hello")],
    ):
        rate = subtitle_alignment_rate(video, srt)
    assert rate == pytest.approx(0.5)


@ffmpeg_only
async def test_quality_report_flags_low_loudness_violation(tmp_path: Path) -> None:
    clip = tmp_path / "quiet.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=320x240:rate=24",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono:d=2",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(clip),
        ],
        check=True,
        capture_output=True,
    )
    rep = await quality_report(clip, n_samples=2)
    assert rep.loudness_lufs is not None
    assert not rep.passed
    assert any("响度" in v for v in rep.violations)
