"""Tests for ffmpeg real-frame video QA checks (aspect ratio, flicker, loop)."""

import subprocess
from pathlib import Path
import pytest
from hevi.motion_rules.video_checks import (
    FFMPEG_BIN,
    check_aspect_ratio,
    check_flicker,
    check_loop_similarity,
    check_video,
)


def _generate_video(output_path: Path, filter_desc: str, duration: float = 2.0, size: str = "540x960", fps: int = 25) -> Path:
    """Helper to generate a real video on the fly with ffmpeg lavfi."""
    cmd = [
        FFMPEG_BIN,
        "-y",
        "-f", "lavfi",
        "-i", filter_desc,
        "-t", str(duration),
        "-r", str(fps),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    assert output_path.exists()
    return output_path


def test_video_aspect_ratio_checks(tmp_path: Path) -> None:
    # 1. 9:16 portrait video (540x960) -> PASS
    portrait_vid = _generate_video(
        tmp_path / "portrait_9_16.mp4",
        "color=c=navy:s=540x960",
        duration=1.0,
    )
    res_portrait = check_aspect_ratio(portrait_vid, target_ratio=(9, 16))
    assert res_portrait.ok is True
    assert res_portrait.width == 540
    assert res_portrait.height == 960

    # 2. 16:9 landscape video (960x540) -> FAIL
    landscape_vid = _generate_video(
        tmp_path / "landscape_16_9.mp4",
        "color=c=navy:s=960x540",
        duration=1.0,
    )
    res_landscape = check_aspect_ratio(landscape_vid, target_ratio=(9, 16))
    assert res_landscape.ok is False
    assert "不符合" in res_landscape.message


def test_video_flicker_normal_vs_flickering(tmp_path: Path) -> None:
    # 1. Normal smooth video (constant color or slow drift) -> PASS
    normal_vid = _generate_video(
        tmp_path / "normal_smooth.mp4",
        "color=c=blue:s=540x960",
        duration=2.0,
        fps=25,
    )
    res_normal = check_flicker(normal_vid, jump_threshold=20.0, max_flicker_frequency=2.0)
    assert res_normal.ok is True
    assert res_normal.jump_count == 0
    assert res_normal.flicker_frequency == 0.0
    assert res_normal.max_brightness_diff < 5.0

    # 2. Intentionally flickering video: alternating black and white every frame -> FAIL
    flicker_vid = _generate_video(
        tmp_path / "extreme_flicker.mp4",
        "color=c=black:s=540x960:d=2:r=25,geq=lum='if(mod(N,2),255,0)'",
        duration=2.0,
        fps=25,
    )
    res_flicker = check_flicker(flicker_vid, jump_threshold=20.0, max_flicker_frequency=2.0)
    assert res_flicker.ok is False
    assert res_flicker.jump_count >= 40  # jumps happen virtually every frame
    assert res_flicker.flicker_frequency > 15.0  # ~24.5 jumps per second
    assert res_flicker.max_brightness_diff > 200.0
    assert "检测到明显画面频闪" in res_flicker.message


def test_video_loop_similarity_checks(tmp_path: Path) -> None:
    # 1. Perfectly loopable video (static canvas with identical start and end) -> PASS
    loop_vid = _generate_video(
        tmp_path / "perfect_loop.mp4",
        "color=c=darkgreen:s=540x960",
        duration=1.5,
    )
    res_loop = check_loop_similarity(loop_vid, similarity_threshold=0.95)
    assert res_loop.ok is True
    assert res_loop.similarity > 0.99
    assert res_loop.mean_abs_diff < 0.01

    # 2. Non-looping video: fades from black to white -> FAIL
    non_loop_vid = _generate_video(
        tmp_path / "non_loop_fade.mp4",
        "color=c=white:s=540x960:d=2:r=25,fade=t=in:st=0:d=2",
        duration=2.0,
        fps=25,
    )
    res_non_loop = check_loop_similarity(non_loop_vid, similarity_threshold=0.95)
    assert res_non_loop.ok is False
    assert res_non_loop.similarity < 0.90
    assert "无法平滑循环" in res_non_loop.message


def test_full_check_video_suite(tmp_path: Path) -> None:
    vid = _generate_video(
        tmp_path / "full_qa.mp4",
        "color=c=gray:s=540x960",
        duration=1.0,
    )
    report = check_video(vid, is_loop=True)
    assert report.ok is True
    assert report.aspect.ok is True
    assert report.flicker.ok is True
    assert report.loop is not None and report.loop.ok is True

    # Text report formatting
    txt = report.format_text()
    assert "PASS (质检合格)" in txt
    assert "宽高比检查: [PASS]" in txt
    assert "闪烁检测:   [PASS]" in txt
