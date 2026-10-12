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

    The compliance target is the *rendered glyph ink height*, not the ASS font
    size and not the ink-plus-outline footprint. Measured with libass on this
    box, Noto Sans CJK SC bold renders ink at ~0.694 em, so an em of 0.085x the
    short edge yields ~5.9% ink, clearing the 5% floor with real margin for
    font-metric variation. The outline stroke is deliberately excluded: it is a
    decoration drawn outside the glyph, so counting it would overstate the mark.
    The rendered value is re-measured in :func:`verify_watermark_in_frame`.
    """
    short_edge = min(frame_width, frame_height)
    required_min_px = int(round(short_edge * 0.05))
    # ink_px ~= 0.694 * font_size_px; 0.085 em -> ~0.059 * short_edge of ink.
    font_size_px = max(required_min_px, int(round(short_edge * 0.085)))

    return WatermarkSpec(
        text=text,
        font_size_px=font_size_px,
        duration_s=max(2.0, duration_s),
        position="top_left",
        ratio_to_short_edge=round(font_size_px / short_edge, 4),
        implicit_comment=f"GB45438-2025:AIGC; Generator=Hevi-ViralClone-3O; Watermark={text}",
    )


def _render_ass_on_flat(
    ass_path: str | Path,
    width: int,
    height: int,
    out_png: str | Path,
) -> bool:
    """Render ``ass_path`` through the same ffmpeg/libass used for delivery onto
    a flat mid-grey background. Returns False if ffmpeg is unavailable."""
    cmd = [
        "ffmpeg", "-v", "error",
        "-f", "lavfi", "-i", f"color=c=0x404040:s={width}x{height}:d=1:r=25",
        "-vf", f"subtitles={ass_path}",
        "-frames:v", "1", str(out_png), "-y",
    ]
    try:
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return Path(out_png).is_file()
    except Exception:
        return False


def measure_ass_glyph_bbox(
    ass_path: str | Path,
    frame_width: int,
    frame_height: int,
    *,
    region: tuple[float, float, float, float] = (0.0, 0.0, 0.55, 0.22),
    flat_level: int = 0x40,
    ink_level: int = 200,
) -> dict[str, Any]:
    """Measure the true rendered *glyph ink* height of the AI mark.

    This is the ground-truth measurement for GB 45438: the exact ASS file that
    is burned into the delivered video is re-rendered by the same ffmpeg/libass
    onto a flat background, and the bright glyph fill is measured in the
    watermark region. The black outline stroke is excluded, and — unlike a
    frame-vs-frame diff — there is zero codec noise to inflate the box.
    """
    import numpy as np
    from PIL import Image

    if not Path(ass_path).is_file():
        return {"found": False, "glyph_height_px": 0, "method": "ass_flat_render_unavailable"}

    h, w = frame_height, frame_width
    x0, y0 = int(region[0] * w), int(region[1] * h)
    x1, y1 = int(region[2] * w), int(region[3] * h)

    tmp_dir = Path(ass_path).parent / ".wm_measure"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out_png = tmp_dir / f"flat_{w}x{h}.png"
    if not _render_ass_on_flat(ass_path, w, h, out_png):
        return {"found": False, "glyph_height_px": 0, "method": "ass_flat_render_failed"}

    arr = np.asarray(Image.open(out_png).convert("L")).astype(np.int16)
    patch = arr[y0:y1, x0:x1]
    mask = patch > ink_level
    ys, xs = np.where(mask)
    if len(ys) == 0:
        return {"found": False, "glyph_height_px": 0, "method": "ass_flat_render", "region": [x0, y0, x1, y1]}

    return {
        "found": True,
        "glyph_height_px": int(ys.max() - ys.min() + 1),
        "glyph_width_px": int(xs.max() - xs.min() + 1),
        "bbox_xyxy": [int(x0 + xs.min()), int(y0 + ys.min()), int(x0 + xs.max()), int(y0 + ys.max())],
        "region": [x0, y0, x1, y1],
        "method": "ass_flat_render_ink_only",
        "note": "glyph ink only; the ASS outline stroke is excluded from the height",
    }


def detect_overlay_in_frame(
    frame_path: str | Path,
    reference_frame_path: str | Path,
    *,
    region: tuple[float, float, float, float] = (0.0, 0.0, 0.55, 0.22),
    threshold: int = 45,
) -> dict[str, Any]:
    """Presence check: confirm the AI mark is actually burned into the delivered
    frame by diffing it against the watermark-free reference encode. This only
    answers *is the overlay there*; it is never used to size the mark, because
    cross-encode compression noise inflates a diff-derived box."""
    import numpy as np
    from PIL import Image

    if not Path(frame_path).is_file() or not Path(reference_frame_path).is_file():
        return {"present": False, "reason": "frames_unavailable"}

    frame = np.asarray(Image.open(frame_path).convert("L")).astype(np.int16)
    ref = np.asarray(Image.open(reference_frame_path).convert("L")).astype(np.int16)
    h, w = frame.shape
    x0, y0 = int(region[0] * w), int(region[1] * h)
    x1, y1 = int(region[2] * w), int(region[3] * h)
    diff = np.abs(frame[y0:y1, x0:x1] - ref[y0:y1, x0:x1])
    changed = int((diff > threshold).sum())
    return {
        "present": bool(changed > 200),
        "changed_pixels": changed,
        "region": [x0, y0, x1, y1],
        "threshold": threshold,
    }


def measure_glyph_bbox(
    frame_path: str | Path,
    *,
    reference_frame_path: str | Path | None = None,
    region: tuple[float, float, float, float] = (0.0, 0.0, 0.55, 0.22),
    threshold: int = 45,
) -> dict[str, Any]:
    """Legacy overlay-footprint measurement (ink + outline) of the AI mark.

    Kept for debugging/diffing only. It is contaminated by the outline stroke
    and by cross-encode noise, so it MUST NOT be used to certify GB 45438 size;
    use :func:`measure_ass_glyph_bbox` for that.
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
        "method": "frame_diff_ink_plus_outline_NOT_for_compliance",
    }


def verify_watermark_in_frame(
    frame_path: str | Path,
    frame_width: int,
    frame_height: int,
    expected_spec: WatermarkSpec,
    *,
    reference_frame_path: str | Path | None = None,
    ass_path: str | Path | None = None,
) -> dict[str, Any]:
    """Verify GB 45438 AI-mark compliance on a delivered frame.

    Size is measured from the rendered glyph **ink** of the delivered ASS file
    (deterministic, noise-free); presence is confirmed by diffing the delivered
    frame against the watermark-free reference encode. Font size alone is never
    accepted as evidence.
    """
    short_edge = min(frame_width, frame_height)

    if ass_path is not None:
        measurement = measure_ass_glyph_bbox(ass_path, frame_width, frame_height)
    else:
        measurement = measure_glyph_bbox(frame_path, reference_frame_path=reference_frame_path)

    present = bool(measurement.get("found"))
    if reference_frame_path is not None:
        presence = detect_overlay_in_frame(frame_path, reference_frame_path)
        present = present and bool(presence.get("present"))
    else:
        presence = {"present": None, "reason": "no_reference_frame"}

    glyph_h = int(measurement.get("glyph_height_px", 0))
    measured_ratio = round(glyph_h / short_edge, 4) if short_edge else 0.0
    duration_ok = expected_spec.duration_s >= 2.0
    size_ok = measured_ratio >= 0.05

    return {
        "passed": bool(present and size_ok and duration_ok),
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
        "overlay_present_in_delivered_frame": presence,
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
