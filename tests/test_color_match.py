"""hevi.assembly.color_match 测试 — lavfi 合成纯色片真 ffmpeg 集成测。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from hevi.assembly.color_match import frame_rgb_mean, match_color_to_reference

_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
ffmpeg_only = pytest.mark.skipif(not _HAS_FFMPEG, reason="needs ffmpeg/ffprobe")


def _make_solid_clip(path: Path, color_hex: str, seconds: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x{color_hex}:size=64x64:duration={seconds}:rate=8",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


@ffmpeg_only
async def test_match_color_pulls_clip_toward_reference(tmp_path: Path) -> None:
    # 参考段是中性灰,待校色段明显偏红——校色后应该更接近参考均值。
    ref_clip = tmp_path / "ref.mp4"
    _make_solid_clip(ref_clip, "808080")
    ref_frame = tmp_path / "ref_frame.png"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(ref_clip), "-vframes", "1", str(ref_frame)],
        check=True,
        capture_output=True,
    )
    ref_mean = frame_rgb_mean(ref_frame)

    biased_clip = tmp_path / "biased.mp4"
    _make_solid_clip(biased_clip, "FF4040")  # 明显偏红

    out = tmp_path / "corrected.mp4"
    result = await match_color_to_reference(biased_clip, ref_mean, out)

    assert out.exists()
    corrected_frame = tmp_path / "corrected_frame.png"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(out), "-vframes", "1", str(corrected_frame)],
        check=True,
        capture_output=True,
    )
    corrected_mean = frame_rgb_mean(corrected_frame)

    dist_before = sum(abs(a - b) for a, b in zip(result["cur_mean"], ref_mean, strict=True))
    dist_after = sum(abs(a - b) for a, b in zip(corrected_mean, ref_mean, strict=True))
    assert dist_after < dist_before


@ffmpeg_only
async def test_match_color_gain_is_clamped_on_extreme_difference(tmp_path: Path) -> None:
    # 参考段极亮,待校色段极暗——增益理论值会远超 clamp 上界,必须被夹住。
    ref_mean = (250.0, 250.0, 250.0)
    dark_clip = tmp_path / "dark.mp4"
    _make_solid_clip(dark_clip, "050505")

    out = tmp_path / "clamped.mp4"
    result = await match_color_to_reference(dark_clip, ref_mean, out, gain_clamp=(0.7, 1.4))

    assert all(g <= 1.4 + 1e-6 for g in result["gain"])
    assert any(g == pytest.approx(1.4) for g in result["gain"])


def test_frame_rgb_mean_reads_solid_color(tmp_path: Path) -> None:
    if not _HAS_FFMPEG:
        pytest.skip("needs ffmpeg")
    clip = tmp_path / "solid.mp4"
    _make_solid_clip(clip, "00FF00")
    frame = tmp_path / "frame.png"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(clip), "-vframes", "1", str(frame)],
        check=True,
        capture_output=True,
    )
    r, g, b = frame_rgb_mean(frame)
    assert g > r and g > b
