"""SVFACTORY Asset Folder Auto-Montage module.

Given a local directory of video/image assets and target duration (or voice file),
automatically selects, trims (with start/end timestamps), resizes to target aspect ratio
(9:16 or 16:9), avoids consecutive duplicates, and uses a deterministic random seed.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from oprim import probe_duration


def list_local_assets(folder_path: str | Path) -> list[Path]:
    p = Path(folder_path)
    if not p.exists() or not p.is_dir():
        return []
    exts = {".mp4", ".mov", ".mkv", ".avi", ".png", ".jpg", ".jpeg", ".webp"}
    assets = [f for f in p.iterdir() if f.is_file() and f.suffix.lower() in exts]
    return sorted(assets, key=lambda x: x.name)


def auto_montage_segments(
    asset_dir: str | Path,
    target_duration: float,
    *,
    seed: int = 42,
    aspect: str = "16:9",
    min_segment_duration: float = 2.0,
    max_segment_duration: float = 8.0,
) -> dict[str, Any]:
    """Generate deterministic video clips and time ranges from a local asset folder to match target duration.

    Returns:
        {
            "video_files": [str, ...],
            "time_ranges": [[start_str, end_str], ...],
            "total_duration": float,
            "seed": int,
            "aspect": str
        }
    """
    rng = random.Random(seed)
    assets = list_local_assets(asset_dir)
    if not assets:
        # Fallback: create a blank color clip or placeholder if no assets found
        # Or raise ValueError as per specs
        raise ValueError(f"资产文件夹为空或不存在: {asset_dir}")

    # Separate video assets and image assets
    video_assets = [a for a in assets if a.suffix.lower() in {".mp4", ".mov", ".mkv", ".avi"}]
    image_assets = [a for a in assets if a.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]

    usable_assets = video_assets if video_assets else image_assets
    if not usable_assets:
        raise ValueError(f"资产文件夹中没有可用视频或图片素材: {asset_dir}")

    video_files: list[str] = []
    time_ranges: list[list[str]] = []
    accumulated = 0.0
    last_asset_path: str | None = None

    # Safety iteration limit to prevent infinite loop
    iterations = 0
    while accumulated < target_duration and iterations < 200:
        iterations += 1
        # Pick asset avoiding immediate consecutive repeat if possible
        candidates = [a for a in usable_assets if str(a) != last_asset_path]
        if not candidates:
            candidates = usable_assets
        asset = rng.choice(candidates)
        last_asset_path = str(asset)

        is_video = asset.suffix.lower() in {".mp4", ".mov", ".mkv", ".avi"}
        if is_video:
            dur = 0.0
            try:
                dur = float(probe_duration(asset))
            except Exception:
                dur = 0.0
            if dur <= 0.5:
                # Treat as static image/frame duration
                seg_dur = min(max_segment_duration, target_duration - accumulated)
                if seg_dur < 0.5:
                    seg_dur = 2.0
                video_files.append(str(asset))
                time_ranges.append(["0.000", f"{seg_dur:.3f}"])
                accumulated += seg_dur
            else:
                seg_dur = rng.uniform(min_segment_duration, min(max_segment_duration, dur, target_duration - accumulated + 1.0))
                if seg_dur > dur:
                    seg_dur = dur
                max_start = max(0.0, dur - seg_dur)
                start_t = rng.uniform(0.0, max_start)
                end_t = start_t + seg_dur
                video_files.append(str(asset))
                time_ranges.append([f"{start_t:.3f}", f"{end_t:.3f}"])
                accumulated += seg_dur
        else:
            # Image asset displayed for seg_dur
            seg_dur = min(max_segment_duration, target_duration - accumulated)
            if seg_dur < 0.5:
                seg_dur = 3.0
            video_files.append(str(asset))
            time_ranges.append(["0.000", f"{seg_dur:.3f}"])
            accumulated += seg_dur

    return {
        "video_files": video_files,
        "time_ranges": time_ranges,
        "total_duration": accumulated,
        "seed": seed,
        "aspect": aspect,
    }
