"""Deterministic visual measurements and the Layer4 visual quality policy.

The measurement contract deliberately contains no business verdict.  A single
policy function, owned by Layer4, maps the measurements to PASS/WARN/BLOCK.
Frames are decoded with PyAV and sampled with bounded timestamp seeks.
"""

from __future__ import annotations

import math
import time
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class VisualQualityMeasurements(BaseModel):
    model_config = ConfigDict(frozen=True)

    duration_ms: int
    frame_count: int
    fps: float
    width: int
    height: int
    black_frame_ratio: float
    freeze_frame_ratio: float
    mean_luma: float
    low_luma_ratio: float
    high_luma_ratio: float
    camera_motion_score: float
    camera_drift_score: float
    shot_count: int
    average_shot_duration_ms: float
    min_shot_duration_ms: float = 0.0
    max_shot_duration_ms: float = 0.0
    expected_frame_count: int | None = None
    actual_frame_count: int
    frame_count_delta: int | None = None
    clock_drift_ms: int | None = None
    analysis_frames: int
    analysis_elapsed_ms: int
    sample_policy: str
    details: dict[str, Any] = Field(default_factory=dict)


class VisualQualityThresholds(BaseModel):
    """Auditable Layer4 policy configuration; adapters do not own thresholds."""

    model_config = ConfigDict(frozen=True)

    black_frame_block_ratio: float = 0.60
    freeze_frame_block_ratio: float = 0.90
    low_luma_block_ratio: float = 0.95
    high_luma_block_ratio: float = 0.95
    camera_drift_warn_score: float = 0.45
    frame_delta_tolerance: int = 1
    clock_tolerance_ms: int = 1000
    planned_shot_count_warn_delta: int = 1


class VisualQualityPolicyDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["PASS", "WARN", "BLOCK"]
    reasons: tuple[str, ...] = ()
    thresholds: VisualQualityThresholds


def _sample_indices(frame_count: int, max_frames: int) -> list[int]:
    count = max(1, min(max_frames, frame_count))
    if count == 1:
        return [0]
    return sorted({round(i * (frame_count - 1) / (count - 1)) for i in range(count)})


def _decode_samples(path: Path, frame_count: int, fps: float, max_frames: int) -> list[Any]:
    import av

    samples: list[Any] = []
    with av.open(str(path)) as container:
        stream: Any = next(s for s in container.streams if s.type == "video")
        for index in _sample_indices(frame_count, max_frames):
            target_seconds = index / max(fps, 1e-6)
            # With an explicit stream, PyAV interprets seek offsets in that
            # stream's time_base (not AV_TIME_BASE). Mixing these units can
            # repeatedly decode the wrong GOP and report a false freeze.
            if stream.time_base is not None:
                timestamp = int(target_seconds / float(stream.time_base))
                container.seek(max(0, timestamp), stream=stream, backward=True)
            else:
                timestamp = int(target_seconds * av.time_base)
                container.seek(max(0, timestamp), backward=True)
            frame: Any = None
            for candidate in container.decode(stream):
                if candidate.pts is None or stream.time_base is None:
                    frame = candidate
                    break
                frame = candidate
                if float(candidate.pts * stream.time_base) >= target_seconds:
                    break
            if frame is not None:
                samples.append(frame.to_ndarray(format="rgb24"))
    if not samples:
        raise ValueError("video contains no decodable frames")
    return samples


def _probe(path: Path) -> tuple[int, int, float, int, int]:
    import av

    with av.open(str(path)) as container:
        stream: Any = next(s for s in container.streams if s.type == "video")
        width, height = int(stream.width), int(stream.height)
        fps = float(stream.average_rate or stream.guessed_rate or 0.0)
        duration_ms = round(float(container.duration or 0) / av.time_base * 1000)
        frame_count = int(stream.frames or 0)
        if duration_ms <= 0 and stream.duration is not None and stream.time_base:
            duration_ms = round(float(stream.duration * stream.time_base) * 1000)
        if frame_count <= 0 and duration_ms > 0 and fps > 0:
            frame_count = round(duration_ms * fps / 1000)
        return width, height, fps, duration_ms, max(frame_count, 1)


def analyze_video(
    path: Path,
    *,
    max_frames: int = 120,
    audio_duration_ms: int | None = None,
    shot_boundaries_ms: list[int] | None = None,
) -> VisualQualityMeasurements:
    """Decode real video samples and return measurements only."""

    started = time.monotonic()
    if not path.is_file() or path.stat().st_size <= 0:
        raise FileNotFoundError(f"video artifact missing or empty: {path}")
    width, height, fps, duration_ms, frame_count = _probe(path)
    frames = _decode_samples(path, frame_count, fps, max_frames)
    import numpy as np

    lumas: list[float] = []
    low: list[float] = []
    high: list[float] = []
    black: list[bool] = []
    motion: list[float] = []
    drift: list[float] = []
    previous: Any = None
    previous_centroid: tuple[float, float] | None = None
    frozen = 0
    for rgb in frames:
        gray = (rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722).astype("float32")
        lumas.append(float(gray.mean()))
        low.append(float((gray < 20.0).mean()))
        high.append(float((gray > 245.0).mean()))
        black.append(float(gray.mean()) < 12.0 and float(np.percentile(gray, 95)) < 25.0)
        small = gray[:: max(1, gray.shape[0] // 64), :: max(1, gray.shape[1] // 64)]
        norm = small / 255.0
        yy, xx = np.mgrid[0 : small.shape[0], 0 : small.shape[1]]
        weight = norm + 1e-6
        centroid = (float((xx * weight).sum() / weight.sum()), float((yy * weight).sum() / weight.sum()))
        if previous is not None:
            pixel_delta = float(np.abs(small - previous).mean() / 255.0)
            motion.append(pixel_delta)
            if pixel_delta <= 0.006:
                frozen += 1
        if previous_centroid is not None:
            diagonal = math.hypot(small.shape[0], small.shape[1]) or 1.0
            drift.append(math.hypot(centroid[0] - previous_centroid[0], centroid[1] - previous_centroid[1]) / diagonal)
        previous, previous_centroid = small, centroid
    boundaries = sorted({0, duration_ms, *(shot_boundaries_ms or [])})
    boundaries = [x for x in boundaries if 0 <= x <= duration_ms]
    if len(boundaries) < 2:
        boundaries = [0, duration_ms]
    shot_durations = [b - a for a, b in pairwise(boundaries) if b >= a]
    expected = round(audio_duration_ms * fps / 1000) if audio_duration_ms is not None and fps > 0 else None
    actual = frame_count
    frame_delta: int | None = actual - expected if expected is not None else None
    clock = duration_ms - audio_duration_ms if audio_duration_ms is not None else None
    return VisualQualityMeasurements(
        duration_ms=duration_ms, frame_count=frame_count, fps=fps, width=width, height=height,
        black_frame_ratio=sum(black) / len(black), freeze_frame_ratio=frozen / max(1, len(frames) - 1),
        mean_luma=float(np.mean(lumas)), low_luma_ratio=float(np.mean(low)), high_luma_ratio=float(np.mean(high)),
        camera_motion_score=float(np.mean(motion)) if motion else 0.0,
        camera_drift_score=float(np.mean(drift)) if drift else 0.0,
        shot_count=len(shot_durations), average_shot_duration_ms=float(np.mean(shot_durations)),
        min_shot_duration_ms=float(min(shot_durations)), max_shot_duration_ms=float(max(shot_durations)),
        expected_frame_count=expected, actual_frame_count=actual, frame_count_delta=frame_delta, clock_drift_ms=clock,
        analysis_frames=len(frames), analysis_elapsed_ms=round((time.monotonic() - started) * 1000),
        sample_policy=f"bounded_timestamp_seek:max_frames={max_frames}",
        details={"black_frame_count": sum(black), "freeze_frame_count": frozen, "shot_boundaries_ms": boundaries},
    )


def evaluate_visual_quality(
    measurements: VisualQualityMeasurements,
    *,
    thresholds: VisualQualityThresholds | None = None,
    planned_shot_count: int | None = None,
    allow_static: bool = False,
) -> VisualQualityPolicyDecision:
    """Layer4-only mapping from evidence to the business gate verdict."""

    policy = thresholds or VisualQualityThresholds()
    block: list[str] = []
    warn: list[str] = []
    if measurements.black_frame_ratio >= policy.black_frame_block_ratio:
        block.append("black_frame_ratio")
    if not allow_static and measurements.freeze_frame_ratio >= policy.freeze_frame_block_ratio:
        block.append("freeze_frame_ratio")
    if measurements.low_luma_ratio >= policy.low_luma_block_ratio:
        block.append("low_luma_ratio")
    if measurements.high_luma_ratio >= policy.high_luma_block_ratio:
        block.append("high_luma_ratio")
    if measurements.camera_drift_score >= policy.camera_drift_warn_score:
        warn.append("camera_drift_score")
    if measurements.frame_count_delta is not None and abs(measurements.frame_count_delta) > policy.frame_delta_tolerance:
        block.append("frame_count_delta")
    if measurements.clock_drift_ms is not None and abs(measurements.clock_drift_ms) > policy.clock_tolerance_ms:
        block.append("clock_drift_ms")
    if planned_shot_count is not None and abs(measurements.shot_count - planned_shot_count) > policy.planned_shot_count_warn_delta:
        warn.append("planned_shot_count")
    status: Literal["PASS", "WARN", "BLOCK"] = "BLOCK" if block else ("WARN" if warn else "PASS")
    return VisualQualityPolicyDecision(status=status, reasons=tuple(block + warn), thresholds=policy)


__all__ = [
    "VisualQualityMeasurements",
    "VisualQualityPolicyDecision",
    "VisualQualityThresholds",
    "analyze_video",
    "evaluate_visual_quality",
]
