"""Measured rendered-text check (``qa.rendered_text_measure``).

Clean-room rewrite of the *measurement method* of the rendered-text
check in ``win4r/video-director`` (MIT; see
VIDEO_DIRECTOR_ATTRIBUTION.md): crop a rendered frame by the text
box, split luminances into two classes with Otsu's method, treat
the smaller class as glyphs, and read the realised cap height and
contrast off the pixels instead of trusting the declared font size.
No text, code or script from the source repository is copied here.

This only adds the measurement layer. It does not repeat the
subtitle-discipline gates (line length, terminology, safe zone in
``hevi/capabilities/subtitle_discipline.py``); call those for the
declaration-side rules and this one for what the render actually
shows.

``box`` is ``[x0, y0, x1, y1]`` in pixels, or fractions of the
frame when every value is in ``(0, 1]``; a ``{"x":..,"y":..,"w":..,
"h":..}`` / ``{"x0":..,"y0":..,"x1":..,"y1":..}`` dict is also
accepted. A measurement is only judged when both a box *and* a
timestamp (``at_sec``) are supplied: without either, the result is
``status="undetermined"`` with ``pass=None`` -- never a pass.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

# Method defaults from the video-director rendered-text method, at a
# 1080-pixel short edge, scaled by the actual short edge like the
# timeline gate floors. Contrast is the ratio of the two class
# median luminances (lighter over darker).
REFERENCE_SHORT_EDGE = 1080.0
DEFAULT_PX_FLOORS: dict[str, float] = {"hook": 84.0, "cta": 48.0, "term": 48.0}
DEFAULT_MIN_CONTRAST_RATIO = 7.0
# Cap height is taken as this fraction of the declared font size in
# the source method (measured on Inter / JetBrains Mono); the same
# factor is used here so a measured cap converts back to font px.
CAP_TO_FONT_FACTOR = 0.72
# Rows whose glyph count is below this share of the crop width are
# treated as anti-aliasing spill, not part of the cap height.
_DENSE_ROW_FRACTION = 0.02


def _normalise_box(box: Any, width: int, height: int) -> tuple[int, int, int, int] | None:
    if box is None:
        return None
    coords: list[float] | None = None
    if isinstance(box, dict):
        if {"x", "y", "w", "h"} <= set(box):
            coords = [box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"]]
        elif {"x0", "y0", "x1", "y1"} <= set(box):
            coords = [box["x0"], box["y0"], box["x1"], box["y1"]]
        elif {"left", "top", "right", "bottom"} <= set(box):
            coords = [box["left"], box["top"], box["right"], box["bottom"]]
    elif isinstance(box, (list, tuple)) and len(box) == 4:
        coords = list(box)
    if coords is None or not all(isinstance(v, (int, float)) for v in coords):
        return None
    values = [float(v) for v in coords]
    if all(0 < v <= 1.0 for v in values):
        values = [values[0] * width, values[1] * height, values[2] * width, values[3] * height]
    x0, y0, x1, y1 = (int(round(v)) for v in values)
    x0 = max(0, min(width - 1, x0))
    y0 = max(0, min(height - 1, y0))
    x1 = max(x0 + 1, min(width, x1))
    y1 = max(y0 + 1, min(height, y1))
    return x0, y0, x1, y1


def _otsu_threshold(hist: Any, total: int) -> int | None:
    """Otsu threshold over a 256-bin histogram; None if no split exists."""
    import numpy as np

    hist = np.asarray(hist, dtype=np.float64)
    if total <= 0:
        return None
    bins = np.arange(256, dtype=np.float64)
    weight_bg = np.cumsum(hist)
    weight_fg = total - weight_bg
    mean_bg = np.cumsum(hist * bins) / np.where(weight_bg == 0, 1, weight_bg)
    total_mean = float(np.sum(hist * bins)) / total
    mean_fg = (total_mean * total - np.cumsum(hist * bins)) / np.where(weight_fg == 0, 1, weight_fg)
    between = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
    between[(weight_bg == 0) | (weight_fg == 0)] = -1.0
    best = int(np.argmax(between))
    if between[best] < 0:
        return None
    return best


def measure_rendered_text(
    image_path: Path | str,
    box: Any,
    role: str,
    *,
    at_sec: float | None = None,
    px_floors: dict[str, float] | None = None,
    min_contrast_ratio: float = DEFAULT_MIN_CONTRAST_RATIO,
) -> dict[str, Any]:
    """Measure rendered text in ``box`` on ``image_path``.

    Returns ``status`` in ``{"pass", "fail", "undetermined"}`` plus
    ``font_px``, ``cap_px`` and ``contrast_ratio`` when measured.
    ``at_sec`` must be supplied (0.0 counts) for a judged result.
    """
    image_path = Path(image_path)
    base: dict[str, Any] = {
        "capability": "qa.rendered_text_measure",
        "image_path": str(image_path),
        "box": box,
        "role": role,
        "at_sec": at_sec,
        "status": "undetermined",
        "pass": None,
        "font_px": None,
        "cap_px": None,
        "contrast_ratio": None,
        "floor_px": None,
    }
    if not image_path.is_file():
        raise CapabilityError(f"qa.rendered_text_measure: image not found: {image_path}")
    if box is None:
        return {**base, "reason": "no box supplied: text was not measured"}
    if at_sec is None:
        return {**base, "reason": "no timestamp supplied: text was not measured"}
    try:
        import numpy as np
    except ImportError:
        return {**base, "reason": "numpy unavailable: text was not measured"}
    with Image.open(image_path) as img:
        width, height = img.size
        region = _normalise_box(box, width, height)
        if region is None:
            return {**base, "reason": f"unusable box: {box!r}"}
        grey = img.convert("L").crop(region)
    arr = np.asarray(grey)
    if arr.size == 0:
        return {**base, "reason": "empty crop"}
    if len(np.unique(arr)) < 2:
        return {**base, "reason": "uniform crop: no two luminance classes to split"}
    hist = np.bincount(arr.ravel(), minlength=256)
    threshold = _otsu_threshold(hist, int(arr.size))
    if threshold is None:
        return {**base, "reason": "Otsu found no split between classes"}
    glyph_mask = arr <= threshold
    bg_mask = ~glyph_mask
    # The smaller class is the glyph class; if the split put most
    # pixels on the dark side, the glyphs are the light class.
    if int(glyph_mask.sum()) > int(bg_mask.sum()):
        glyph_mask = bg_mask
        bg_mask = ~glyph_mask
    if int(glyph_mask.sum()) == 0 or int(bg_mask.sum()) == 0:
        return {**base, "reason": "Otsu split left one class empty"}
    glyph_values = arr[glyph_mask].astype(np.float64)
    bg_values = arr[bg_mask].astype(np.float64)
    glyph_median = float(np.median(glyph_values))
    bg_median = float(np.median(bg_values))
    lighter = max(glyph_median, bg_median)
    darker = min(glyph_median, bg_median)
    contrast = lighter / max(darker, 1.0)

    # Cap height: vertical extent of dense glyph rows (top of the
    # densest rows to their baseline), trimming sparse spill rows.
    row_counts = glyph_mask.sum(axis=1)
    min_dense = max(2.0, _DENSE_ROW_FRACTION * arr.shape[1])
    dense_rows = [i for i, count in enumerate(row_counts) if count >= min_dense]
    if not dense_rows:
        return {**base, "reason": "no dense glyph rows in crop"}
    cap_px = float(dense_rows[-1] - dense_rows[0] + 1)
    font_px = cap_px / CAP_TO_FONT_FACTOR

    floors = dict(DEFAULT_PX_FLOORS)
    if px_floors:
        floors.update(px_floors)
    short_edge = min(width, height)
    result = {**base, "cap_px": round(cap_px, 2), "font_px": round(font_px, 2),
              "contrast_ratio": round(contrast, 3)}
    if role not in floors:
        return {**result, "reason": f"no size floor for role {role!r}: measured only"}
    floor_px = floors[role] * (short_edge / REFERENCE_SHORT_EDGE)
    result["floor_px"] = round(floor_px, 2)
    failures = []
    if font_px < floor_px:
        failures.append(f"font {font_px:.1f}px below floor {floor_px:.1f}px")
    if contrast < min_contrast_ratio:
        failures.append(f"contrast {contrast:.2f} below {min_contrast_ratio}")
    if failures:
        return {**result, "status": "fail", "pass": False,
                "reason": "; ".join(failures)}
    return {**result, "status": "pass", "pass": True,
            "reason": "measured font size and contrast meet the floors"}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {}
    if params.get("at_sec") is not None:
        kwargs["at_sec"] = float(params["at_sec"])
    if params.get("min_contrast_ratio") is not None:
        kwargs["min_contrast_ratio"] = float(params["min_contrast_ratio"])
    if params.get("px_floors") is not None:
        kwargs["px_floors"] = {str(k): float(v) for k, v in params["px_floors"].items()}
    report = measure_rendered_text(params["image_path"], params.get("box"), str(params["role"]), **kwargs)
    report_path = out_dir / "rendered_text_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "status": report["status"],
            "pass": report["pass"],
            "font_px": report["font_px"],
            "contrast_ratio": report["contrast_ratio"],
        },
    )


def register_rendered_text_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.rendered_text_measure",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "image_path": {"type": "string"},
                    "box": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                    "role": {"type": "string"},
                    "at_sec": {"type": "number", "minimum": 0},
                    "min_contrast_ratio": {"type": "number", "exclusiveMinimum": 0},
                    "px_floors": {"type": "object"},
                },
                "required": ["image_path", "role"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Measured rendered-text check (Otsu split, cap height "
                "/ 0.72, class median contrast): hook/cta/term floors "
                "84/48/48px at 1080 short edge and contrast >= 7.0. "
                "No box or no timestamp returns undetermined, never a "
                "pass. Measurement layer only; declaration-side text "
                "rules stay in subtitle_discipline."
            ),
            line="qa",
        )
    )
    return ["qa.rendered_text_measure"]


register_rendered_text_capabilities_once()
