"""Batch estimation, selective failed-shot retry, and merge validation.

Implements workbench-level engineering safety capabilities:
1. Batch generation estimate: shot count, total duration, estimated CPU run time.
2. One-click retry: only retries failed tasks, preserving successful shots.
3. Merge pre-check: validates that all required clip files exist and are non-empty.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MissingClipPrerequisiteError(RuntimeError):
    """Raised when one or more shot video clips or audio tracks are missing before merge."""


@dataclass
class BatchEstimate:
    shot_count: int
    total_duration_s: float
    model: str
    resolution: tuple[int, int]
    estimated_cpu_seconds: float
    breakdown: dict[str, float]
    resource_ok: bool = True
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def estimate_batch(
    shots: list[Any],
    *,
    engine: str = "sdturbo_cpu",
    tts_engine: str = "piper",
    width: int = 1080,
    height: int = 1920,
) -> BatchEstimate:
    """Pre-run estimation of shot count, duration, and CPU processing time."""
    shot_count = len(shots)
    total_duration_s = 0.0
    for s in shots:
        if isinstance(s, dict):
            dur = float(s.get("duration_s") or s.get("duration") or 5.0)
        elif hasattr(s, "duration_s"):
            dur = float(getattr(s, "duration_s"))
        elif hasattr(s, "duration"):
            dur = float(getattr(s, "duration"))
        else:
            dur = 5.0
        total_duration_s += dur

    # Estimated CPU seconds based on benchmarked single-shot CPU runtimes:
    # - Keyframe generation (SD-Turbo 2 steps CPU with TAESD): ~3.5s / shot
    # - Voiceover synthesis (Piper TTS): ~0.35s / shot
    # - Ken Burns camera move encoding (FFmpeg libx264 1080x1920): ~1.2s / shot
    # - Track muxing & subtitle burn-in (FFmpeg concat + ASS filter): ~2.5s base
    kf_sec = round(shot_count * 3.5, 2)
    tts_sec = round(shot_count * 0.35, 2)
    clip_sec = round(shot_count * 1.2, 2)
    mux_sec = 2.5
    total_cpu_sec = round(kf_sec + tts_sec + clip_sec + mux_sec, 2)

    breakdown = {
        "keyframe_generation_s": kf_sec,
        "tts_synthesis_s": tts_sec,
        "video_clip_render_s": clip_sec,
        "audio_mix_and_assembly_s": mux_sec,
    }

    note = (
        f"预估镜头数: {shot_count}，总片长: {total_duration_s:.1f}s，"
        f"CPU 预估总耗时: {total_cpu_sec:.1f}s"
    )

    return BatchEstimate(
        shot_count=shot_count,
        total_duration_s=round(total_duration_s, 2),
        model=engine,
        resolution=(width, height),
        estimated_cpu_seconds=total_cpu_sec,
        breakdown=breakdown,
        resource_ok=True,
        note=note,
    )


@dataclass
class ShotTask:
    shot_id: str
    prompt: str = ""
    tts_text: str = ""
    duration_s: float = 5.0
    status: str = "pending"  # pending | running | success | failed
    error_message: str | None = None
    clip_path: str | None = None
    retry_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def retry_failed_shots(
    tasks: list[ShotTask],
    run_shot_fn: Callable[[ShotTask], None],
) -> tuple[list[ShotTask], int]:
    """Selectively re-run only tasks marked with status == 'failed'.

    Preserves successful tasks untouched, ensuring idempotent retry.
    Returns (updated_tasks, retried_count).
    """
    retried_count = 0
    for task in tasks:
        if task.status == "failed":
            task.retry_count += 1
            task.status = "running"
            task.error_message = None
            try:
                run_shot_fn(task)
                task.status = "success"
                retried_count += 1
            except Exception as e:
                task.status = "failed"
                task.error_message = str(e)
                retried_count += 1
                logger.error("Retry failed for shot %s: %s", task.shot_id, e)
    return tasks, retried_count


def validate_merge_prerequisites(
    clip_paths: list[Path | str],
    audio_path: Path | str | None = None,
) -> list[Path]:
    """Validate that every shot clip and required audio exists and is non-empty.

    Raises:
        MissingClipPrerequisiteError: If any file does not exist, is empty,
            or is not a regular file.
    """
    if not clip_paths:
        raise MissingClipPrerequisiteError("合并前校验失败：镜头列表为空，无可用分镜")

    missing: list[str] = []
    verified: list[Path] = []

    for item in clip_paths:
        p = Path(item)
        if not p.exists():
            missing.append(f"{p} (文件不存在)")
        elif not p.is_file():
            missing.append(f"{p} (非普通文件)")
        elif p.stat().st_size == 0:
            missing.append(f"{p} (文件为空 0 bytes)")
        else:
            verified.append(p)

    if audio_path is not None:
        ap = Path(audio_path)
        if not ap.exists():
            missing.append(f"{ap} (音频文件不存在)")
        elif not ap.is_file():
            missing.append(f"{ap} (音频非普通文件)")
        elif ap.stat().st_size == 0:
            missing.append(f"{ap} (音频文件为空 0 bytes)")

    if missing:
        raise MissingClipPrerequisiteError(
            f"合并前前置校验失败，缺少必要文件或产物损坏:\n" + "\n".join(f" - {m}" for m in missing)
        )

    return verified
