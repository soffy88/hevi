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
    backend: str = "auto"  # "auto" | "scenedetect" | "ffmpeg"

    def detect(self, path: str, probe: VideoProbe) -> list[ShotBoundaryEvidence]:
        if self.backend in ("auto", "scenedetect"):
            try:
                from scenedetect import ContentDetector, detect

                fps = (
                    (probe.fps_num / probe.fps_den)
                    if (getattr(probe, "fps_num", None) and getattr(probe, "fps_den", None))
                    else (getattr(probe, "frame_rate", None) or 25.0)
                )
                scene_list = detect(
                    path,
                    ContentDetector(
                        threshold=float(self.threshold * 80.0 if self.threshold <= 1.0 else self.threshold),
                        min_scene_len=max(5, int(fps * self.minimum_shot_duration_ms / 1000)),
                    ),
                )
                points: list[ShotBoundaryEvidence] = []
                last = None
                for _start, end in scene_list:
                    sec = getattr(end, "seconds", None)
                    ts = round(float(sec if sec is not None else end.get_seconds()) * 1000)
                    if ts < probe.duration_ms and (last is None or ts - last >= self.minimum_shot_duration_ms):
                        points.append(
                            ShotBoundaryEvidence(
                                timestamp_ms=ts,
                                method="scenedetect-content-v1",
                                source="AUTO_SCENE_DETECT",
                            )
                        )
                        last = ts
                if points or self.backend == "scenedetect":
                    return points
            except Exception:
                if self.backend == "scenedetect":
                    raise

        command = [
            "ffmpeg",
            "-hide_banner",
            "-i",
            path,
            "-vf",
            f"select='gt(scene,{self.threshold})',showinfo",
            "-an",
            "-f",
            "null",
            "-",
        ]
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=300, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"SHOT_DETECTION_FAILED:{exc}") from exc
        if completed.returncode != 0:
            raise RuntimeError(f"SHOT_DETECTION_FAILED:{completed.stderr[-400:]}")
        points = []
        last = None
        for raw in re.findall(r"pts_time:([0-9.]+)", completed.stderr):
            timestamp = round(float(raw) * 1000)
            if timestamp <= 0 or timestamp >= probe.duration_ms:
                continue
            if last is None or (timestamp - last >= self.minimum_shot_duration_ms):
                points.append(
                    ShotBoundaryEvidence(
                        timestamp_ms=timestamp,
                        method=self.version,
                        source="AUTO_SCENE_DETECT",
                    )
                )
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
