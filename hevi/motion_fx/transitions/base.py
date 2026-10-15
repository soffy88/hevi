"""Base transition definitions and frame processing utilities for Motion FX."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple, Union

import cv2
import numpy as np


@dataclass
class VideoInfo:
    width: int
    height: int
    fps: float
    duration: float
    total_frames: int
    has_audio: bool


def probe_video(video_path: Union[str, Path]) -> VideoInfo:
    """Probe video file using ffprobe and return metadata."""
    path = Path(video_path)
    if not path.is_file():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    cmd = [
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    info = json.loads(proc.stdout)

    v_stream = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    if not v_stream:
        raise ValueError(f"No video stream found in {video_path}")

    width = int(v_stream["width"])
    height = int(v_stream["height"])

    # Parse fps
    r_fps = v_stream.get("r_frame_rate", "30/1")
    if "/" in r_fps:
        num, denom = r_fps.split("/")
        fps = float(num) / float(denom) if float(denom) != 0 else 30.0
    else:
        fps = float(r_fps)

    # Parse duration
    duration = float(v_stream.get("duration") or info.get("format", {}).get("duration", 0.0))

    # Total frames
    nb_frames = v_stream.get("nb_frames")
    if nb_frames and nb_frames.isdigit():
        total_frames = int(nb_frames)
    else:
        total_frames = max(1, int(round(duration * fps)))

    has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))

    return VideoInfo(
        width=width,
        height=height,
        fps=fps,
        duration=duration,
        total_frames=total_frames,
        has_audio=has_audio,
    )


# Type for transition render function:
# (frame_a: np.ndarray, frame_b: np.ndarray, progress: float, params: dict) -> np.ndarray
TransitionFunc = Callable[[np.ndarray, np.ndarray, float, Dict[str, Any]], np.ndarray]
