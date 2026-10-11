"""Pure QA verdict from measured frame/audio statistics (the omodul layer
decodes the MP4; this module only judges the numbers)."""

from __future__ import annotations

from typing import Any

import numpy as np


def frame_stats(frames: np.ndarray) -> dict[str, float]:
    """frames: (N, h, w) grayscale uint8/float sampled at a fixed rate."""
    fr = frames.astype(np.float32)
    if len(fr) == 0:
        raise ValueError("no frames decoded")
    diffs = np.abs(np.diff(fr, axis=0)).mean((1, 2)) if len(fr) > 1 else np.array([0.0])
    return {
        "frames_sampled": int(len(fr)),
        "motion_mean": float(diffs.mean()),
        "static_ratio": float((diffs < 0.6).mean()),
        "black_ratio": float((fr.mean((1, 2)) < 12).mean()),
        "dark_textcard_ratio": float(((fr < 40).mean((1, 2)) > 0.85).mean()),
        "luma_std_mean": float(fr.std((1, 2)).mean()),
    }


def judge(
    *,
    stats: dict[str, float],
    duration_s: float,
    has_video: bool,
    has_audio: bool,
    mean_volume_db: float | None,
    width: int,
    height: int,
    expect_size: tuple[int, int],
    min_motion: float,
    max_static_ratio: float,
    max_black_ratio: float | None,
    max_dark_ratio: float | None,
    min_volume_db: float,
    expect_audio: bool,
    min_duration_s: float,
) -> dict[str, Any]:
    checks: dict[str, bool] = {
        "has_video": has_video,
        "resolution_matches_spec": (width, height) == tuple(expect_size),
        f"duration_ge_{min_duration_s:g}s": duration_s >= min_duration_s,
        f"motion_mean_ge_{min_motion:g}": stats["motion_mean"] >= min_motion,
        f"static_ratio_lt_{max_static_ratio:g}": stats["static_ratio"] < max_static_ratio,
        # a frame with almost no luma variance across the whole clip = blank/solid card
        "not_blank_luma_std_ge_8": stats["luma_std_mean"] >= 8.0,
    }
    not_applicable: list[str] = []
    if max_black_ratio is None:
        not_applicable.append("black_ratio")
    else:
        checks[f"black_ratio_lt_{max_black_ratio:g}"] = stats["black_ratio"] < max_black_ratio
    if max_dark_ratio is None:
        not_applicable.append("dark_textcard_ratio")
    else:
        checks[f"dark_textcard_ratio_lt_{max_dark_ratio:g}"] = stats["dark_textcard_ratio"] < max_dark_ratio
    if expect_audio:
        checks["has_audio"] = has_audio
        checks[f"audio_mean_volume_gt_{min_volume_db:g}dB"] = mean_volume_db is not None and mean_volume_db > min_volume_db
    failed = [k for k, v in checks.items() if not v]
    return {
        "checks": checks,
        "checks_not_applicable": not_applicable,
        "failed_checks": failed,
        "pass": not failed,
    }


__all__ = ["frame_stats", "judge"]
