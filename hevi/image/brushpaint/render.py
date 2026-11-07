"""Rendering: stills and paint-itself videos from brush scenes.

Stills draw the stroke list once at a given reveal progress.  Videos
use a two-canvas scheme so a whole clip costs little more than the
stroke count itself:

* paint phase -- a persistent canvas accumulates strokes in reveal
  order (each stroke is drawn exactly once, with its sway offset frozen
  at its appearance time); a second canvas accumulates only the
  non-swaying strokes.
* hold phase -- the finished painting stays alive: each frame is the
  non-sway canvas plus the swaying strokes redrawn at the current sway
  phase, so swirls and water keep breathing without repainting
  thousands of static dabs per frame.

Frames are piped to ffmpeg (libx264).  No network, no GPU, no cost.
"""

from __future__ import annotations

import math
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from .engine import Scene, Stroke, build_strokes, draw_stroke, new_canvas
from .scene import parse_scene

_SWAY_OMEGA = math.tau / 7.0  # one sway cycle ~7 s


def sway_offset(stroke: Stroke, t: float) -> tuple[float, float]:
    if stroke.sway <= 0:
        return 0.0, 0.0
    ph = stroke.sway_phase + t * _SWAY_OMEGA
    return (
        stroke.sway * math.sin(ph),
        stroke.sway * 0.35 * math.cos(ph * 1.3),
    )


def render_still(
    scene: Scene,
    width: int,
    height: int,
    *,
    progress: float = 1.0,
    sway_time: float = 0.0,
    grain: bool = True,
) -> Image.Image:
    """Render one frame of the painting at reveal ``progress`` (0..1)."""
    if not 0.0 <= progress <= 1.0:
        raise ValueError("progress must be within [0, 1]")
    strokes = build_strokes(scene, width, height)
    img = new_canvas(scene, width, height)
    draw = ImageDraw.Draw(img)
    limit = progress * 1.02  # overshoot so p=1 always completes the picture
    for s in strokes:
        if s.order <= limit:
            dx, dy = sway_offset(s, sway_time)
            draw_stroke(draw, s, dx, dy)
    if grain:
        img = _add_grain(img, scene.seed)
    return img


def _add_grain(img: Image.Image, seed: int) -> Image.Image:
    """Deterministic paper grain (seeded numpy noise, value-only)."""
    rng = np.random.default_rng(seed * 7919 + 13)
    arr = np.asarray(img).astype(np.int16)
    noise = rng.normal(0.0, 4.5, arr.shape[:2])[..., None]
    out = np.clip(arr + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(out, "RGB")


def _ease(t: float) -> float:
    t = min(1.0, max(0.0, t))
    smooth = t * t * (3.0 - 2.0 * t)
    return 0.3 * t + 0.7 * smooth


def render_paint_video(
    scene: Scene,
    out_path: str | Path,
    width: int,
    height: int,
    *,
    seconds: float = 20.0,
    fps: int = 12,
    hold_frac: float = 0.28,
) -> dict[str, Any]:
    """Render the painting painting itself -> MP4.  Returns stats."""
    if seconds <= 0:
        raise ValueError("seconds must be > 0")
    if fps <= 0:
        raise ValueError("fps must be > 0")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    strokes = build_strokes(scene, width, height)
    total_frames = max(2, round(seconds * fps))
    hold_frames = max(1, round(total_frames * hold_frac))
    paint_frames = max(1, total_frames - hold_frames)

    canvas_all = new_canvas(scene, width, height)
    draw_all = ImageDraw.Draw(canvas_all)
    canvas_base = new_canvas(scene, width, height)
    draw_base = ImageDraw.Draw(canvas_base)
    sway_strokes = [s for s in strokes if s.sway > 0]

    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{width}x{height}", "-r", str(fps),
        "-i", "-",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-crf", "20", "-preset", "veryfast",
        str(out_path),
    ]
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    assert proc.stdin is not None
    try:
        idx = 0
        for f in range(paint_frames):
            t = f / fps
            target = _ease(f / max(1, paint_frames - 1)) * 1.02
            while idx < len(strokes) and strokes[idx].order <= target:
                s = strokes[idx]
                if s.sway > 0:
                    dx, dy = sway_offset(s, t)
                    draw_stroke(draw_all, s, dx, dy)
                else:
                    draw_stroke(draw_all, s)
                    draw_stroke(draw_base, s)
                idx += 1
            proc.stdin.write(canvas_all.tobytes())
        # Any stroke the easing left behind lands before the hold phase.
        while idx < len(strokes):
            s = strokes[idx]
            if s.sway <= 0:
                draw_stroke(draw_base, s)
            idx += 1
        for f in range(hold_frames):
            t = (paint_frames + f) / fps
            frame = canvas_base.copy()
            draw = ImageDraw.Draw(frame)
            for s in sway_strokes:
                dx, dy = sway_offset(s, t)
                draw_stroke(draw, s, dx, dy)
            proc.stdin.write(frame.tobytes())
    finally:
        proc.stdin.close()
    rc = proc.wait()
    if rc != 0 or not out_path.is_file():
        raise RuntimeError(f"ffmpeg failed rendering {out_path} (rc={rc})")
    return {
        "mp4": str(out_path),
        "strokes": len(strokes),
        "sway_strokes": len(sway_strokes),
        "frames": total_frames,
        "paint_frames": paint_frames,
        "hold_frames": hold_frames,
        "fps": fps,
        "seconds": round(total_frames / fps, 2),
        "render_seconds": round(time.perf_counter() - started, 2),
    }


def render_spec_still(
    spec: dict[str, Any], width: int, height: int, *, progress: float = 1.0
) -> Image.Image:
    return render_still(parse_scene(spec), width, height, progress=progress)


def render_spec_video(
    spec: dict[str, Any],
    out_path: str | Path,
    width: int,
    height: int,
    *,
    seconds: float = 20.0,
    fps: int = 12,
) -> dict[str, Any]:
    return render_paint_video(
        parse_scene(spec), out_path, width, height, seconds=seconds, fps=fps
    )
