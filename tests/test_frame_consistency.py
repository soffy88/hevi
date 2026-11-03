"""Tests for frame_consistency (report-only endpoint check)."""

from __future__ import annotations

import shutil
import subprocess

import pytest
from PIL import Image

from hevi.capabilities.frame_consistency import (
    check_clip_endpoints,
    frame_similarity,
)


def _solid(path, rgb, size=(64, 36)):
    Image.new("RGB", size, rgb).save(path)


def test_identical_frames_score_zero_mad_and_unit_ssim(tmp_path) -> None:
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    _solid(a, (200, 30, 40))
    _solid(b, (200, 30, 40))
    scores = frame_similarity(a, b)
    assert scores["mad"] == 0.0
    assert scores["ssim"] == pytest.approx(1.0)


def _checkerboard(path, invert=False, size=(64, 36), block=8):
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(size[1]):
        for x in range(size[0]):
            bit = ((x // block) + (y // block)) % 2
            if invert:
                bit = 1 - bit
            v = 255 if bit else 0
            px[x, y] = (v, v, v)
    img.save(path)


def test_different_frames_score_positive_mad_and_lower_ssim(tmp_path) -> None:
    # Flat colours are a bad SSIM probe (two flat fields score ~0.89
    # on luminance alone), so use inverted checkerboards instead.
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    _checkerboard(a)
    _checkerboard(b, invert=True)
    scores = frame_similarity(a, b)
    assert scores["mad"] > 100
    assert scores["ssim"] is not None and scores["ssim"] < 0.5


def test_missing_design_frame_fails_loudly(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        frame_similarity(tmp_path / "nope.png", tmp_path / "also_nope.png")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_clip_endpoints_report_only_even_when_thresholds_missed(tmp_path) -> None:
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "color=c=black:s=64x36:d=1",
            "-f", "lavfi", "-i", "color=c=white:s=64x36:d=1",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0",
            "-pix_fmt", "yuv420p", str(clip),
        ],
        check=True,
    )
    design_first = tmp_path / "white.png"
    design_last = tmp_path / "black.png"
    _solid(design_first, (255, 255, 255))
    _solid(design_last, (0, 0, 0))
    # Clip runs black -> white, but the design claims the opposite:
    # both ends miss the thresholds, yet the check must NOT raise.
    report = check_clip_endpoints(
        design_first, design_last, clip,
        thresholds={"mad_max": 10.0, "ssim_min": 0.9},
        work_dir=tmp_path / "work",
    )
    assert report["verdict"] == "report_only"
    assert report["meets_threshold"] == {"first": False, "last": False}
    assert report["first"]["mad"] > 200
    assert report["last"]["mad"] > 200
    assert (tmp_path / "work" / "clip_first.png").exists()
    assert (tmp_path / "work" / "clip_last.png").exists()
    # The extracted endpoints must be the real ends, not middle frames:
    # the clip runs black -> white, so first is dark, last is bright.
    import numpy as np

    first_px = np.asarray(
        Image.open(tmp_path / "work" / "clip_first.png").convert("L")
    ).mean()
    last_px = np.asarray(
        Image.open(tmp_path / "work" / "clip_last.png").convert("L")
    ).mean()
    assert first_px < 10
    assert last_px > 245


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_clip_endpoints_missing_clip_fails_loudly(tmp_path) -> None:
    design = tmp_path / "design.png"
    _solid(design, (10, 20, 30))
    with pytest.raises(FileNotFoundError):
        check_clip_endpoints(design, design, tmp_path / "nope.mp4")
