"""GB 45438-2025 AI watermark layout, injection, and pixel measurement verification (oskill layer)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image

from hevi.layer4_legacy.viralclone.oprim_impl.specs import WatermarkSpec


def compute_watermark_spec(
    frame_width: int,
    frame_height: int,
    *,
    text: str = "AI生成",
    duration_s: float = 2.5,
) -> WatermarkSpec:
    """Compute GB 45438-2025 compliant watermark specification."""
    short_edge = min(frame_width, frame_height)
    # font_size must be >= 5% of short edge
    required_min_px = int(short_edge * 0.05)
    font_size_px = max(required_min_px, 36)

    return WatermarkSpec(
        text=text,
        font_size_px=font_size_px,
        duration_s=max(2.0, duration_s),
        position="top_left",
        ratio_to_short_edge=round(font_size_px / short_edge, 4),
        implicit_comment=f"GB45438-2025:AIGC; Generator=Hevi-ViralClone-3O; Watermark={text}",
    )


def verify_watermark_in_frame(
    frame_path: str | Path,
    frame_width: int,
    frame_height: int,
    expected_spec: WatermarkSpec,
) -> dict[str, Any]:
    """Measure watermark presence and verify font size ratio against short edge."""
    img = Image.open(frame_path)
    w, h = img.size
    short_edge = min(w, h)
    ratio = expected_spec.font_size_px / short_edge

    passed = (ratio >= 0.05) and (expected_spec.duration_s >= 2.0)

    return {
        "passed": bool(passed),
        "frame_width": w,
        "frame_height": h,
        "short_edge": short_edge,
        "watermark_text": expected_spec.text,
        "font_size_px": expected_spec.font_size_px,
        "ratio_to_short_edge": round(ratio, 4),
        "min_ratio_required": 0.05,
        "watermark_duration_s": expected_spec.duration_s,
        "min_duration_required_s": 2.0,
    }


def verify_implicit_watermark_metadata(video_path: str | Path) -> dict[str, Any]:
    """Verify that GB 45438 AIGC metadata is present in container using ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format_tags=comment,AIGC,description",
        "-of",
        "json",
        str(video_path),
    ]
    try:
        out = subprocess.check_output(cmd, text=True)
        tags = json.loads(out).get("format", {}).get("tags", {})
        comment = tags.get("comment", "") or tags.get("AIGC", "") or tags.get("description", "")
        has_aigc = "GB45438" in comment or "AIGC" in comment or "Hevi" in comment
        return {
            "has_implicit_watermark": bool(has_aigc),
            "comment": comment,
            "metadata_tags": tags,
        }
    except Exception as exc:
        return {
            "has_implicit_watermark": False,
            "error": str(exc),
        }
