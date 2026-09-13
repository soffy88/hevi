"""Deterministic scene-change boundaries using ffmpeg's scene filter."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from .models import ShotBoundaryEvidence, VideoProbe


@dataclass(frozen=True)
class ShotBoundaryDetector:
    threshold: float = 0.35
    minimum_shot_duration_ms: int = 500
    version: str = "ffmpeg-scene-v1"

    def detect(self, path: str, probe: VideoProbe) -> list[ShotBoundaryEvidence]:
        command = [
            "ffmpeg", "-hide_banner", "-i", path, "-vf",
            f"select='gt(scene,{self.threshold})',showinfo", "-an", "-f", "null", "-",
        ]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"SHOT_DETECTION_FAILED:{exc}") from exc
        if completed.returncode != 0:
            raise RuntimeError(f"SHOT_DETECTION_FAILED:{completed.stderr[-400:]}")
        points: list[ShotBoundaryEvidence] = []
        last = 0
        for raw in re.findall(r"pts_time:([0-9.]+)", completed.stderr):
            timestamp = round(float(raw) * 1000)
            if timestamp - last >= self.minimum_shot_duration_ms and timestamp < probe.duration_ms:
                points.append(ShotBoundaryEvidence(
                    timestamp_ms=timestamp,
                    method=self.version,
                    source="AUTO_SCENE_DETECT",
                ))
                last = timestamp
        return points


def validate_boundaries(
    starts_ends: list[tuple[int, int]], duration_ms: int, *, tolerance_ms: int = 100
) -> list[str]:
    errors: list[str] = []
    if not starts_ends:
        return ["BOUNDARY_INVALID:empty"]
    if starts_ends[0][0] != 0:
        errors.append("first_start_not_zero")
    if abs(starts_ends[-1][1] - duration_ms) > tolerance_ms:
        errors.append("last_end_not_duration")
    for index, (start, end) in enumerate(starts_ends):
        if end <= start:
            errors.append(f"non_positive_duration:{index}")
        if index and start != starts_ends[index - 1][1]:
            errors.append(f"gap_or_overlap:{index}")
    return errors
