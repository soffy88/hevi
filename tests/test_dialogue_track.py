"""hevi.assembly.dialogue_track 测试 — lavfi 合成音频真 ffmpeg 集成测。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from hevi.assembly.dialogue_track import (
    DialogueCue,
    build_ambient_bed,
    build_dialogue_track,
    find_cut_point_violations,
    resolve_cut_points,
)

_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
ffmpeg_only = pytest.mark.skipif(not _HAS_FFMPEG, reason="needs ffmpeg/ffprobe")


def _make_tone(path: Path, seconds: float, freq: int = 440) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={freq}:duration={seconds}",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def _duration_s(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return float(out)


@ffmpeg_only
async def test_build_ambient_bed_single_segment_copies(tmp_path: Path) -> None:
    seg = tmp_path / "seg.wav"
    _make_tone(seg, 1.0)
    out = tmp_path / "ambient.wav"
    result = await build_ambient_bed([seg], output_path=out)
    assert result == out
    assert out.exists()


@ffmpeg_only
async def test_build_ambient_bed_crossfades_multiple_segments(tmp_path: Path) -> None:
    segs = []
    for i in range(3):
        p = tmp_path / f"seg{i}.wav"
        _make_tone(p, 2.0, freq=300 + i * 100)
        segs.append(p)
    out = tmp_path / "ambient.wav"
    result = await build_ambient_bed(segs, output_path=out, crossfade_s=0.3)
    assert result is not None
    # 3 段各 2s,交叉淡化 0.3s 两次 → 总时长 ≈ 6 - 2*0.3 = 5.4s
    assert _duration_s(out) == pytest.approx(5.4, abs=0.15)


async def test_build_ambient_bed_empty_returns_none(tmp_path: Path) -> None:
    result = await build_ambient_bed([], output_path=tmp_path / "nope.wav")
    assert result is None


@ffmpeg_only
async def test_build_dialogue_track_places_cues_and_pads_total_duration(tmp_path: Path) -> None:
    line1 = tmp_path / "line1.wav"
    line2 = tmp_path / "line2.wav"
    _make_tone(line1, 1.0)
    _make_tone(line2, 1.0, freq=600)
    cues = [
        DialogueCue(audio_path=line1, start_ms=0),
        DialogueCue(audio_path=line2, start_ms=3000),
    ]
    out = tmp_path / "dialogue.wav"
    result = await build_dialogue_track(cues, output_path=out, total_duration_ms=5000)
    assert result == out
    assert _duration_s(out) == pytest.approx(5.0, abs=0.1)


async def test_build_dialogue_track_empty_returns_none(tmp_path: Path) -> None:
    result = await build_dialogue_track(
        [], output_path=tmp_path / "nope.wav", total_duration_ms=1000
    )
    assert result is None


# ── 句边界硬校验(纯函数,无 ffmpeg 依赖) ──────────────────────────────


def test_find_cut_point_violations_detects_cut_inside_window() -> None:
    violations = find_cut_point_violations([3900], [(2000, 4000)], min_gap_ms=200)
    assert len(violations) == 1
    assert violations[0].cut_time_ms == 3900
    assert violations[0].window == (1800, 4200)
    # 离右边界(4200)比左边界(1800)近 → 应该建议挪到右边界外。
    assert violations[0].resolved_time_ms == 4201


def test_find_cut_point_violations_clean_cut_in_gap_reports_nothing() -> None:
    violations = find_cut_point_violations([1000], [(2000, 4000)], min_gap_ms=200)
    assert violations == []


def test_resolve_cut_points_fixes_violation_and_leaves_clean_ones_alone() -> None:
    resolved = resolve_cut_points(
        [1000, 3000, 6000], [(2000, 4000)], min_gap_ms=200, max_search_ms=3000
    )
    assert resolved[0] == 1000  # 本来就在间隙里,不动
    assert resolved[2] == 6000  # 同上
    assert resolved[1] != 3000  # 落进窗口的那个被挪走了
    # 挪走之后确认真的不在(含安全边距的)窗口里了
    assert not (1800 <= resolved[1] <= 4200)


def test_resolve_cut_points_raises_when_no_safe_gap_within_range() -> None:
    # 对白窗口极宽(0-100000ms),剪辑点在正中央,附近(max_search_ms 范围内)完全没有间隙。
    with pytest.raises(ValueError, match="找不到"):
        resolve_cut_points([50000], [(0, 100000)], min_gap_ms=200, max_search_ms=3000)
