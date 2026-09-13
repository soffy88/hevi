"""CPU-only motion evidence from bounded grayscale frame samples."""

from __future__ import annotations

import math
import statistics
import subprocess
from itertools import pairwise

from .models import MotionClass, MotionEvidence, VideoProbe


class MotionAnalyzer:
    version = "ffmpeg-graydelta-v1"

    def __init__(self, sample_count: int = 24) -> None:
        self.sample_count = max(2, min(sample_count, 120))

    def analyze(self, path: str, probe: VideoProbe) -> MotionEvidence:
        if probe.duration_ms <= 0:
            raise RuntimeError("MOTION_ANALYSIS_FAILED:invalid_duration")
        fps = 2.0
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path,
            "-vf", f"fps={fps},scale=64:36,format=gray",
            "-frames:v", str(self.sample_count), "-f", "rawvideo", "-",
        ]
        try:
            completed = subprocess.run(command, capture_output=True, timeout=300, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"MOTION_ANALYSIS_FAILED:{exc}") from exc
        if completed.returncode != 0:
            raise RuntimeError(f"MOTION_ANALYSIS_FAILED:{completed.stderr[-300:].decode(errors='replace')}")
        width, height = 64, 36
        frame_size = width * height
        frames = [completed.stdout[i:i + frame_size] for i in range(0, len(completed.stdout), frame_size)]
        frames = [frame for frame in frames if len(frame) == frame_size]
        deltas: list[float] = []
        for before, after in pairwise(frames):
            deltas.append(sum(abs(a - b) for a, b in zip(before, after, strict=False)) / frame_size / 255)
        if not deltas:
            raise RuntimeError("MOTION_ANALYSIS_FAILED:no_frames")
        ordered = sorted(deltas)
        p90 = ordered[min(len(ordered) - 1, math.ceil(len(ordered) * 0.9) - 1)]
        mean = statistics.fmean(deltas)
        median = statistics.median(deltas)
        motion_class = (
            MotionClass.STATIC if median < 0.015 else
            MotionClass.LOW if median < 0.05 else
            MotionClass.MEDIUM if median < 0.12 else MotionClass.HIGH
        )
        return MotionEvidence(
            median_frame_delta=median,
            mean_frame_delta=mean,
            p90_frame_delta=p90,
            motion_class=motion_class,
            sample_count=len(frames),
            method=self.version,
        )
