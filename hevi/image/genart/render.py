"""Rendering for the generative-art engine: stills and looping video.

Stills are drawn with chunked additive compositing (particles drawn
in chunks onto black layers, accumulated in float32, then soft-clip
tone mapped) which gives the classic flow-field glow without any GPU.
Video frames reuse the same compositor; for ``flowfield`` the loop is
exact by construction (see :mod:`hevi.image.genart.engine`), for
``julia`` the constant orbits with the loop period.

Frames are piped to ffmpeg as rawvideo -- nothing is written to a
frame directory, which keeps disk use at zero beyond the output file.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from .engine import FlowField, GenartSpec, julia_mu, simulate_flowfield

__all__ = [
    "loop_life",
    "render_flow_frame",
    "render_julia_frame",
    "render_still",
    "render_video",
]

_CHUNK = 256  # particles per additive chunk
_BANDS = 4  # brightness bands per trail


# ---------------------------------------------------------------------------
# Compositing helpers
# ---------------------------------------------------------------------------


def _bg_accumulator(spec: GenartSpec) -> np.ndarray:
    """Float accumulator pre-filled so empty areas tone-map to the bg."""
    bg = np.array(spec.palette.background, dtype=np.float64) / 255.0
    # invert  out = 1 - exp(-acc * exposure)  for the background level
    acc0 = -np.log(np.clip(1.0 - bg, 1e-6, 1.0)) / spec.exposure
    acc = np.empty((spec.height, spec.width, 3), dtype=np.float32)
    acc[:] = acc0.astype(np.float32)
    return acc


def _tonemap(acc: np.ndarray, exposure: float) -> Image.Image:
    out = 1.0 - np.exp(-acc * np.float32(exposure))
    out = np.clip(out, 0.0, 1.0) ** 0.92
    return Image.fromarray((out * 255.0 + 0.5).astype(np.uint8), "RGB")


def _draw_trails(
    acc: np.ndarray,
    points_list: list[np.ndarray],
    colors: list[tuple[float, float, float]],
    *,
    width_px: int = 1,
    breaks_over: float = 40.0,
) -> None:
    """Additively draw polylines (split into brightness bands) into acc.

    ``points_list[i]`` is an ``(M, 2)`` array of pixel coords ordered
    tail -> head; brightness ramps up towards the head.  Segments
    longer than ``breaks_over`` px (edge wraps) are not drawn.
    """
    h, w = acc.shape[:2]
    for start in range(0, len(points_list), _CHUNK):
        layer = Image.new("RGB", (w, h), (0, 0, 0))
        draw = ImageDraw.Draw(layer)
        for pts, col in zip(
            points_list[start : start + _CHUNK],
            colors[start : start + _CHUNK],
        ):
            if len(pts) < 2:
                continue
            m = len(pts) - 1  # number of segments
            for band in range(_BANDS):
                a = int(band * m / _BANDS)
                b = int((band + 1) * m / _BANDS)
                if b <= a:
                    continue
                seg = pts[a : b + 1]
                jumps = np.hypot(*np.diff(seg, axis=0).T) if len(seg) > 1 else []
                if len(jumps) and float(np.max(jumps)) > breaks_over:
                    # split at the wrap jump; draw the clean runs only
                    cut = int(np.argmax(jumps)) + 1
                    runs = [seg[:cut], seg[cut:]]
                else:
                    runs = [seg]
                scale = 0.25 + 0.75 * ((band + 1) / _BANDS) ** 1.5
                rgb = tuple(int(min(255.0, c * scale)) for c in col)
                for run in runs:
                    if len(run) >= 2:
                        draw.line(
                            [tuple(p) for p in run.tolist()],
                            fill=rgb,
                            width=width_px,
                        )
        acc += np.asarray(layer, dtype=np.float32) / 255.0


def _particle_colors(spec: GenartSpec, hues: np.ndarray) -> list[tuple[float, float, float]]:
    lut = spec.palette.lut(256)
    idx = np.clip((hues * 255).astype(np.int64), 0, 255)
    return [tuple(float(c) for c in lut[i]) for i in idx]


# ---------------------------------------------------------------------------
# Flow field frames
# ---------------------------------------------------------------------------


def loop_life(total_frames: int, requested_life: int) -> int:
    """Largest divisor of ``total_frames`` not exceeding the request.

    Video loops are exact only when the particle lifetime divides
    the frame count; this picks the closest such lifetime.
    """
    best = 1
    for d in range(1, int(total_frames**0.5) + 1):
        if total_frames % d == 0:
            for cand in (d, total_frames // d):
                if cand <= requested_life and cand > best:
                    best = cand
    return best


def render_flow_frame(
    spec: GenartSpec,
    sim: FlowField,
    frame: int,
    total_frames: int,
    life: int,
) -> Image.Image:
    """One video frame of the flow field at loop position ``frame``."""
    ages = (frame + sim.phases) % life
    trail = min(spec.trail, life)
    colors = _particle_colors(spec, sim.hues)
    points_list: list[np.ndarray] = []
    frame_colors: list[tuple[float, float, float]] = []
    traj = sim.trajectories
    for i in range(traj.shape[0]):
        a = int(ages[i])
        lo = max(0, a - trail + 1)
        if a - lo < 1:
            continue
        points_list.append(traj[i, lo : a + 1])
        frame_colors.append(colors[i])
    acc = _bg_accumulator(spec)
    _draw_trails(acc, points_list, frame_colors, breaks_over=spec.step_size * 6)
    pulse = 0.94 + 0.06 * float(np.cos(2.0 * np.pi * (frame % total_frames) / total_frames))
    return _tonemap(acc, spec.exposure * pulse)


def _render_flow_still(spec: GenartSpec, sim: FlowField) -> Image.Image:
    colors = _particle_colors(spec, sim.hues)
    acc = _bg_accumulator(spec)
    _draw_trails(
        acc,
        [sim.trajectories[i] for i in range(sim.trajectories.shape[0])],
        colors,
        breaks_over=spec.step_size * 6,
    )
    return _tonemap(acc, spec.exposure)


# ---------------------------------------------------------------------------
# Julia frames
# ---------------------------------------------------------------------------


def render_julia_frame(spec: GenartSpec, theta: float = 0.0) -> Image.Image:
    mu = julia_mu(spec, theta)
    lut = spec.palette.lut(1024)
    t = np.sqrt(np.clip(mu / spec.max_iter, 0.0, 1.0))
    idx = np.clip((t * 1023).astype(np.int64), 0, 1023)
    img = lut[idx]
    interior = mu >= spec.max_iter
    if interior.any():
        img[interior] = np.array(spec.palette.background, dtype=np.float32)
    return Image.fromarray((np.clip(img, 0, 255) + 0.5).astype(np.uint8), "RGB")


# ---------------------------------------------------------------------------
# Public renders
# ---------------------------------------------------------------------------


def render_still(spec: GenartSpec) -> tuple[Image.Image, dict[str, Any]]:
    """Render a finished still; returns (image, stats)."""
    started = time.perf_counter()
    if spec.algorithm == "julia":
        img = render_julia_frame(spec, 0.0)
        stats = {"algorithm": "julia", "max_iter": spec.max_iter}
    else:
        sim = simulate_flowfield(spec)
        img = _render_flow_still(spec, sim)
        stats = {
            "algorithm": "flowfield",
            "particles": int(sim.trajectories.shape[0]),
            "particle_life": int(sim.trajectories.shape[1] - 1),
        }
    stats.update(
        {
            "seed": spec.seed,
            "palette": spec.palette.name,
            "size": f"{spec.width}x{spec.height}",
            "render_seconds": round(time.perf_counter() - started, 2),
            "cost": 0.0,
        }
    )
    return img, stats


def render_video(
    spec: GenartSpec,
    out_path: Path | str,
    *,
    seconds: float = 10.0,
    fps: int = 24,
) -> dict[str, Any]:
    """Render a seamlessly looping MP4; returns stats.

    Raises RuntimeError with ffmpeg's stderr if encoding fails --
    a failed render is reported, never faked.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    total_frames = max(1, int(round(seconds * fps)))
    started = time.perf_counter()

    if spec.algorithm == "flowfield":
        life = loop_life(total_frames, spec.particle_life)
        sim_spec = spec
        if life != spec.particle_life:
            from dataclasses import replace

            sim_spec = replace(spec, particle_life=life)
        sim = simulate_flowfield(sim_spec)

        def frame_at(f: int) -> Image.Image:
            return render_flow_frame(spec, sim, f, total_frames, life)

        extra = {"particles": int(sim.trajectories.shape[0]), "loop_life": life}
    else:

        def frame_at(f: int) -> Image.Image:
            return render_julia_frame(spec, 2.0 * np.pi * f / total_frames)

        extra = {"max_iter": spec.max_iter}

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{spec.width}x{spec.height}",
        "-r",
        str(fps),
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "18",
        "-preset",
        "medium",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    try:
        for f in range(total_frames):
            proc.stdin.write(frame_at(f).tobytes())
        proc.stdin.close()
        stderr = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
        rc = proc.wait()
    except BrokenPipeError:
        stderr = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
        rc = proc.wait()
        raise RuntimeError(f"ffmpeg broke the pipe (rc={rc}): {stderr[-800:]}")
    if rc != 0:
        raise RuntimeError(f"ffmpeg failed (rc={rc}): {stderr[-800:]}")

    stats = {
        "algorithm": spec.algorithm,
        "seed": spec.seed,
        "palette": spec.palette.name,
        "size": f"{spec.width}x{spec.height}",
        "frames": total_frames,
        "fps": fps,
        "seconds": round(total_frames / fps, 2),
        "render_seconds": round(time.perf_counter() - started, 2),
        "file_bytes": out_path.stat().st_size,
        "cost": 0.0,
        **extra,
    }
    return stats
