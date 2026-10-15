#!/usr/bin/env python3
"""Generate a clean, text-free 16:9 source video for the dirstyle E2E run (B3).

The DIRSTYLE_FIX_R3 task forbids any source that carries burned-in
subtitles, watermarks, logos or captions.  This script renders a clean
1920x1080 scene frame-by-frame with PIL: a graded sky, a distant hill
ridge and a dark human silhouette walking across the frame.  There is no
text, caption, timestamp or logo anywhere in the picture.

Output: output/dirstyle_e2e/source_clean.mp4 (h264, yuv420p, 12s, 30fps).
"""

from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output" / "dirstyle_e2e" / "source_clean.mp4"
FRAMES = ROOT / "output" / "dirstyle_e2e" / "_source_frames"

W, H = 1920, 1080
FPS = 30
DURATION_S = 12.0
TOTAL = int(FPS * DURATION_S)


def _sky(draw: ImageDraw.ImageDraw, t: float) -> None:
    """Vertical gradient sky, warm at the horizon, slowly drifting."""
    for y in range(H):
        f = y / H
        # deep teal-blue at the top -> warm amber near the horizon line
        r = int(30 + 210 * f**1.6)
        g = int(60 + 150 * f**1.6)
        b = int(110 - 40 * f**1.6)
        # gentle horizontal light drift over time
        drift = int(8 * math.sin(2 * math.pi * (f + t)))
        draw.line([(0, y), (W, y)], fill=(max(0, r + drift), max(0, g + drift), max(0, b)))


def _ridge(draw: ImageDraw.ImageDraw, t: float) -> None:
    """A distant hill ridge (solid dark band), no thin strokes."""
    base = int(H * 0.72)
    pts = []
    for x in range(0, W + 1, 40):
        y = base + int(40 * math.sin(x / 260.0 + t * 2 * math.pi))
        pts.append((x, y))
    pts += [(W, H), (0, H)]
    draw.polygon(pts, fill=(24, 34, 46))


def _figure(draw: ImageDraw.ImageDraw, cx: int, cy: int, phase: float) -> None:
    """Dark human silhouette (filled), arms/legs swinging with *phase*."""
    s = 2.0
    head_r = int(30 * s)
    # head (filled disc)
    draw.ellipse(
        [cx - head_r, cy - 150 * s - head_r, cx + head_r, cy - 150 * s + head_r],
        fill=(16, 20, 28),
    )
    # torso
    draw.line([(cx, cy - 120 * s), (cx, cy - 20 * s)], fill=(16, 20, 28), width=int(30 * s))
    # arms
    swing = math.sin(phase) * 60 * s
    draw.line(
        [(cx, cy - 105 * s), (cx - 55 * s - swing, cy - 15 * s)],
        fill=(16, 20, 28),
        width=int(22 * s),
    )
    draw.line(
        [(cx, cy - 105 * s), (cx + 55 * s + swing, cy - 15 * s)],
        fill=(16, 20, 28),
        width=int(22 * s),
    )
    # legs
    leg = math.sin(phase) * 55 * s
    draw.line(
        [(cx, cy - 20 * s), (cx - 34 * s - leg, cy + 90 * s)], fill=(16, 20, 28), width=int(26 * s)
    )
    draw.line(
        [(cx, cy - 20 * s), (cx + 34 * s + leg, cy + 90 * s)], fill=(16, 20, 28), width=int(26 * s)
    )


def render() -> None:
    FRAMES.mkdir(parents=True, exist_ok=True)
    for i in range(TOTAL):
        t = i / TOTAL
        img = Image.new("RGB", (W, H), (20, 30, 50))
        d = ImageDraw.Draw(img)
        _sky(d, t)
        _ridge(d, t)
        # figure walks left -> right across the lower-middle of the frame
        cx = int(W * (0.15 + 0.7 * t))
        cy = int(H * 0.82)
        _figure(d, cx, cy, t * 2 * math.pi * 4)
        img.save(FRAMES / f"f_{i:05d}.png")
        if i % 60 == 0:
            print(f"  frame {i}/{TOTAL}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-framerate",
        str(FPS),
        "-i",
        str(FRAMES / "f_%05d.png"),
        "-c:v",
        "libx264",
        "-crf",
        "18",
        "-preset",
        "fast",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(OUT),
    ]
    print("Encoding:", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)
    print(f"Clean source written: {OUT}")


if __name__ == "__main__":
    sys.exit(render() or 0)
