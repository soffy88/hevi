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
    """Compute GB 45438-2025 compliant watermark specification.

    The compliance target is the *rendered glyph height*, not the ASS font size.
    libass cap-height is roughly 0.83x the em size for mixed Latin/CJK text, so
    the em size is chosen to make the measured glyph bbox clear 5% of the short
    edge; the true ratio is then verified by pixel measurement in
    :func:`verify_watermark_in_frame`.
    """
    short_edge = min(frame_width, frame_height)
    required_min_px = int(round(short_edge * 0.05))
    # 0.068 em ~= 0.056 * short_edge rendered glyph height (measured, see DONE).
    font_size_px = max(required_min_px, int(round(short_edge * 0.068)))

    return WatermarkSpec(
        text=text,
        font_size_px=font_size_px,
        duration_s=max(2.0, duration_s),
        position="top_left",
        ratio_to_short_edge=round(font_size_px / short_edge, 4),
        implicit_comment=f"GB45438-2025:AIGC; Generator=Hevi-ViralClone-3O; Watermark={text}",
    )


def measure_glyph_bbox(
    frame_path: str | Path,
    *,
    reference_frame_path: str | Path | None = None,
    region: tuple[float, float, float, float] = (0.0, 0.0, 0.55, 0.22),
    threshold: int = 45,
) -> dict[str, Any]:
    """Measure the AI-mark glyph bounding box in a real rendered frame.

    When a watermark-free reference frame (same timestamp, e.g. the pre-subtitle
    ``visual_cuts`` render) is supplied, the bbox is derived from the absolute
    pixel difference inside the watermark region, which isolates the glyphs from
    arbitrary footage. Returns an empty bbox when no mark is found.
    """
    import numpy as np
    from PIL import Image

    frame = np.asarray(Image.open(frame_path).convert("L")).astype(np.int16)
    h, w = frame.shape
    x0 = int(region[0] * w)
    y0 = int(region[1] * h)
    x1 = int(region[2] * w)
    y1 = int(region[3] * h)
    patch = frame[y0:y1, x0:x1]

    if reference_frame_path is not None and Path(reference_frame_path).is_file():
        ref = np.asarray(Image.open(reference_frame_path).convert("L")).astype(np.int16)
        ref_patch = ref[y0:y1, x0:x1]
        diff = np.abs(patch - ref_patch)
        mask = diff > threshold
    else:
        # Fallback: bright glyph fill against a darker local median.
        med = float(np.median(patch))
        mask = patch > max(200, med + 40)

    ys, xs = np.where(mask)
    if len(ys) == 0:
        return {"found": False, "glyph_height_px": 0, "glyph_width_px": 0, "region": [x0, y0, x1, y1]}

    bbox = [int(x0 + xs.min()), int(y0 + ys.min()), int(x0 + xs.max()), int(y0 + ys.max())]
    return {
        "found": True,
        "glyph_height_px": int(ys.max() - ys.min() + 1),
        "glyph_width_px": int(xs.max() - xs.min() + 1),
        "bbox_xyxy": bbox,
        "region": [x0, y0, x1, y1],
    }


def verify_watermark_in_frame(
    frame_path: str | Path,
    frame_width: int,
    frame_height: int,
    expected_spec: WatermarkSpec,
    *,
    reference_frame_path: str | Path | None = None,
) -> dict[str, Any]:
    """Measure the *actual rendered glyph height* and verify it against GB 45438."""
    short_edge = min(frame_width, frame_height)
    measurement = measure_glyph_bbox(frame_path, reference_frame_path=reference_frame_path)
    glyph_h = int(measurement.get("glyph_height_px", 0))
    measured_ratio = round(glyph_h / short_edge, 4) if short_edge else 0.0
    duration_ok = expected_spec.duration_s >= 2.0
    size_ok = measured_ratio >= 0.05

    return {
        "passed": bool(measurement.get("found") and size_ok and duration_ok),
        "frame_width": frame_width,
        "frame_height": frame_height,
        "short_edge": short_edge,
        "watermark_text": expected_spec.text,
        "ass_font_size_px": expected_spec.font_size_px,
        "measured_glyph_height_px": glyph_h,
        "measured_ratio": measured_ratio,
        "min_ratio_required": 0.05,
        "watermark_duration_s": expected_spec.duration_s,
        "min_duration_required_s": 2.0,
        "glyph_bbox": measurement.get("bbox_xyxy"),
        "measurement": measurement,
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
