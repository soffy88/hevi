"""Transition execution engine for Motion FX."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Union

import cv2
import numpy as np

from hevi.motion_fx.beat import snap_to_grid
from hevi.motion_fx.transitions.base import TransitionFunc, VideoInfo, probe_video
from hevi.motion_fx.transitions.glass_refract import render_glass_refract
from hevi.motion_fx.transitions.line_to_structure import render_line_to_structure
from hevi.motion_fx.transitions.water_ripple import render_water_ripple

REGISTRY: Dict[str, TransitionFunc] = {
    "line_to_structure": render_line_to_structure,
    "water_ripple": render_water_ripple,
    "glass_refract": render_glass_refract,
}


def register_transition(name: str, func: TransitionFunc) -> None:
    """Register a custom transition function."""
    REGISTRY[name] = func


def get_transition_func(kind: str) -> TransitionFunc:
    """Lookup a transition function by name."""
    if kind not in REGISTRY:
        available = ", ".join(sorted(REGISTRY.keys()))
        raise ValueError(f"Unknown transition kind '{kind}'. Available: {available}")
    return REGISTRY[kind]


def apply_transition(
    clip_a: Union[str, Path],
    clip_b: Union[str, Path],
    kind: str,
    dur: float,
    params: Optional[Dict[str, Any]] = None,
    out: Optional[Union[str, Path]] = None,
    start: Optional[float] = None,
) -> Path:
    """Apply a motion-fx transition between clip_a and clip_b.

    Args:
        clip_a: Path to first video file (mp4).
        clip_b: Path to second video file (mp4).
        kind: Transition name ('line_to_structure', 'water_ripple', 'glass_refract').
        dur: Transition overlap duration in seconds.
        params: Optional dict of transition parameters (e.g. bpm, division, snap_start, etc.).
        out: Path for the output mp4 file. If None, creates a file in the same directory.
        start: Optional timestamp in seconds where the transition begins in clip_a.
               If bpm is present in params, start can be snapped to the grid.
               If None, defaults to clip_a.duration - dur.

    Returns:
        Path to the generated H.264 yuv420p mp4 file.
    """
    path_a = Path(clip_a).resolve()
    path_b = Path(clip_b).resolve()

    if not path_a.is_file():
        raise FileNotFoundError(f"clip_a does not exist: {path_a}")
    if not path_b.is_file():
        raise FileNotFoundError(f"clip_b does not exist: {path_b}")

    render_fn = get_transition_func(kind)
    cfg = dict(params or {})

    info_a = probe_video(path_a)
    info_b = probe_video(path_b)

    width = info_a.width
    height = info_a.height
    fps = info_a.fps

    # Clamp dur so it does not exceed clip durations
    dur = max(0.1, min(dur, info_a.duration, info_b.duration))

    # Grid snapping if BPM requested
    bpm = cfg.get("bpm")
    division = cfg.get("division", 4)

    if start is not None:
        t_start = float(start)
        if bpm:
            t_start = snap_to_grid(t_start, bpm=float(bpm), division=division)
        t_cut = max(0.0, min(t_start, max(0.0, info_a.duration - dur)))
    else:
        t_cut = max(0.0, info_a.duration - dur)
        if bpm and cfg.get("snap_start"):
            t_cut = snap_to_grid(t_cut, bpm=float(bpm), division=division)
            t_cut = max(0.0, min(t_cut, max(0.0, info_a.duration - dur)))

    n_pre = max(0, int(round(t_cut * fps)))
    n_trans = max(2, int(round(dur * fps)))

    # Post frames from clip_b
    n_b_total = max(1, int(round(info_b.duration * fps)))
    n_post = max(0, n_b_total - n_trans)

    if out is None:
        out_path = path_a.parent / f"{path_a.stem}_{path_b.stem}_{kind}.mp4"
    else:
        out_path = Path(out).resolve()

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Temporary raw video file or direct pipe
    # Direct ffmpeg pipe for video
    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{width}x{height}",
        "-pix_fmt", "bgr24",
        "-r", f"{fps:.4f}",
        "-i", "-",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(out_path),
    ]

    pipe_proc = subprocess.Popen(
        ffmpeg_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    cap_a = cv2.VideoCapture(str(path_a))
    cap_b = cv2.VideoCapture(str(path_b))

    try:
        last_frame_a = None
        # 1. Stream pre-transition frames from clip_a
        for _ in range(n_pre):
            ret, frame = cap_a.read()
            if not ret or frame is None:
                if last_frame_a is not None:
                    frame = last_frame_a
                else:
                    frame = np.zeros((height, width, 3), dtype=np.uint8)
            else:
                last_frame_a = frame
            if frame.shape[:2] != (height, width):
                frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_LINEAR)
            pipe_proc.stdin.write(frame.tobytes())

        # 2. Transition frames
        # Read frames for transition window
        trans_a_frames: list[np.ndarray] = []
        for _ in range(n_trans):
            ret, frame = cap_a.read()
            if not ret or frame is None:
                frame = last_frame_a if last_frame_a is not None else np.zeros((height, width, 3), dtype=np.uint8)
            else:
                last_frame_a = frame
            if frame.shape[:2] != (height, width):
                frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_LINEAR)
            trans_a_frames.append(frame)

        trans_b_frames: list[np.ndarray] = []
        last_frame_b = None
        for _ in range(n_trans):
            ret, frame = cap_b.read()
            if not ret or frame is None:
                frame = last_frame_b if last_frame_b is not None else np.zeros((height, width, 3), dtype=np.uint8)
            else:
                last_frame_b = frame
            if frame.shape[:2] != (height, width):
                frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_LINEAR)
            trans_b_frames.append(frame)

        for i in range(n_trans):
            p = float(i) / float(n_trans - 1) if n_trans > 1 else 0.5
            fa = trans_a_frames[i]
            fb = trans_b_frames[i]
            rendered = render_fn(fa, fb, p, cfg)
            if rendered.shape[:2] != (height, width):
                rendered = cv2.resize(rendered, (width, height), interpolation=cv2.INTER_LINEAR)
            pipe_proc.stdin.write(rendered.tobytes())

        # 3. Stream post-transition frames from clip_b
        for _ in range(n_post):
            ret, frame = cap_b.read()
            if not ret or frame is None:
                if last_frame_b is not None:
                    frame = last_frame_b
                else:
                    frame = np.zeros((height, width, 3), dtype=np.uint8)
            else:
                last_frame_b = frame
            if frame.shape[:2] != (height, width):
                frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_LINEAR)
            pipe_proc.stdin.write(frame.tobytes())

    finally:
        cap_a.release()
        cap_b.release()
        if pipe_proc.stdin:
            pipe_proc.stdin.close()
        stderr = pipe_proc.stderr.read() if pipe_proc.stderr else b""
        retcode = pipe_proc.wait()
        if retcode != 0:
            raise RuntimeError(f"FFmpeg encoding failed (exit code {retcode}): {stderr.decode('utf-8', errors='replace')}")

    # Audio handling: If both clips had audio, crossfade audio into output
    if info_a.has_audio and info_b.has_audio:
        _mux_audio(path_a, path_b, out_path, t_cut, dur, fps)

    return out_path


def _mux_audio(
    path_a: Path,
    path_b: Path,
    out_video: Path,
    t_cut: float,
    dur: float,
    fps: float,
) -> None:
    """Optional audio crossfade muxing using ffmpeg acrossfade filter."""
    temp_muxed = out_video.parent / f"{out_video.stem}_mux.mp4"
    audio_filter = f"[0:a][1:a]acrossfade=d={dur:.3f}:c1=tri:c2=tri[aout]"
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(path_a),
        "-i", str(path_b),
        "-i", str(out_video),
        "-filter_complex", audio_filter,
        "-map", "2:v:0",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(temp_muxed),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0 and temp_muxed.is_file() and temp_muxed.stat().st_size > 0:
        temp_muxed.replace(out_video)
