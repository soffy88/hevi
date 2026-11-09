"""S13: the hyperframes ffmpeg fallback must not freeze on a static card."""

from __future__ import annotations

import subprocess
from pathlib import Path

from hevi.providers.hyperframes.compiler import HyperClip, HyperComposition
from hevi.providers.hyperframes.fallback import render_fallback_composition


def _mean_abs_diff(a: Path, b: Path) -> float:
    from PIL import Image, ImageChops, ImageStat

    left = Image.open(a).convert("RGB")
    right = Image.open(b).convert("RGB")
    return float(ImageStat.Stat(ImageChops.difference(left, right)).mean[0])


def test_fallback_frames_move_within_one_clip(tmp_path: Path) -> None:
    comp = HyperComposition(
        title="FROZEN?",
        width=160,
        height=284,
        fps=5,
        clips=[HyperClip(0.0, 2.0, "这一张字卡不应该完全静止", kind="title")],
    )
    out = render_fallback_composition(comp, tmp_path / "card.mp4", width=160, height=284, fps=5)
    assert out.is_file() and out.stat().st_size > 0

    first = tmp_path / "f1.png"
    last = tmp_path / "f9.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "0.2", "-i", str(out),
                    "-frames:v", "1", str(first)], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "1.0", "-i", str(out),
                    "-frames:v", "1", str(last)], check=True)
    # The push-in plus the travelling bar change many pixels between frames.
    assert _mean_abs_diff(first, last) > 0.5
