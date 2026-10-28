"""Cover family spec and thumbnail readability gate (``design.cover_family``).

A cover family is a fixed, checkable identity, not a mood: one
primary colour, one secondary colour, one title colour on one
background colour, one headline font, one title zone, and one
brand-mark zone, all pinned as fractions of the frame so the same
layout holds at any size. Zones are checked for staying inside the
frame and for not overlapping each other: a brand mark sitting on
top of the title is a layout bug, not a style choice.

The readability gate answers one narrow question: if this cover is
shrunk to 200 pixels wide -- the size it is actually browsed at --
can the main title still be read? It answers it arithmetically:
the title's point size is scaled by 200 / canvas width, and the
title/background contrast ratio is computed exactly. Two thresholds
must both pass: the scaled title must be at least 14 pixels in the
projection, and the contrast ratio must be at least 4.5:1.

Honest limit, stated in every report: when no rendered image is
supplied, this is an arithmetic projection, not a look at the
picture. It cannot see a busy photo behind the words, a thin font
weight, or a title that wraps badly. It must never be reported as
"the thumbnail was viewed and reads clearly". When an image is
supplied, the helper below still only measures the downscaled title
zone's tonal variation -- a weak signal that the zone is not blank,
not a reading test -- and says so.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

THUMBNAIL_WIDTH_PX = 200
MIN_SCALED_TITLE_PX = 14.0
MIN_CONTRAST_RATIO = 4.5
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _check_hex(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _HEX_RE.match(value):
        raise CapabilityError(
            f"design.cover_family: {field} must be a #RRGGBB hex colour, "
            f"got {value!r}"
        )
    return value.lower()


def _check_zone(zone: Any, field: str) -> dict[str, float]:
    if not isinstance(zone, dict):
        raise CapabilityError(
            f"design.cover_family: {field} must be a zone object with "
            "x, y, w, h as fractions of the frame"
        )
    out: dict[str, float] = {}
    for key in ("x", "y", "w", "h"):
        value = zone.get(key)
        if not isinstance(value, (int, float)) \
                or isinstance(value, bool) or not 0 <= float(value) <= 1:
            raise CapabilityError(
                f"design.cover_family: {field}.{key} must be a fraction "
                f"between 0 and 1, got {value!r}"
            )
        out[key] = float(value)
    if out["w"] <= 0 or out["h"] <= 0:
        raise CapabilityError(
            f"design.cover_family: {field} must have positive w and h"
        )
    if out["x"] + out["w"] > 1 + 1e-9 or out["y"] + out["h"] > 1 + 1e-9:
        raise CapabilityError(
            f"design.cover_family: {field} runs past the frame edge"
        )
    return out


def _overlap(a: dict[str, float], b: dict[str, float]) -> float:
    x = max(0.0, min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]))
    y = max(0.0, min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"]))
    return x * y


def _luminance(hex_colour: str) -> float:
    def channel(value: int) -> float:
        c = value / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r = channel(int(hex_colour[1:3], 16))
    g = channel(int(hex_colour[3:5], 16))
    b = channel(int(hex_colour[5:7], 16))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG relative-luminance contrast ratio between two hex colours."""
    light = max(_luminance(foreground), _luminance(background))
    dark = min(_luminance(foreground), _luminance(background))
    return (light + 0.05) / (dark + 0.05)


def define_cover_spec(
    *,
    primary_color: str,
    secondary_color: str,
    title_color: str,
    background_color: str,
    font_family: str,
    title_zone: dict[str, Any],
    brand_zone: dict[str, Any],
    canvas_width_px: int = 1080,
    canvas_height_px: int = 1920,
) -> dict[str, Any]:
    """Pin a cover family spec, rejecting structural mistakes outright."""
    if not font_family or not isinstance(font_family, str):
        raise CapabilityError(
            "design.cover_family: font_family must be a non-empty string"
        )
    if not isinstance(canvas_width_px, int) or canvas_width_px <= 0 \
            or not isinstance(canvas_height_px, int) or canvas_height_px <= 0:
        raise CapabilityError(
            "design.cover_family: canvas size must be positive integers"
        )
    title = _check_zone(title_zone, "title_zone")
    brand = _check_zone(brand_zone, "brand_zone")
    if _overlap(title, brand) > 0:
        raise CapabilityError(
            "design.cover_family: title_zone and brand_zone overlap; "
            "move the brand mark out of the title area"
        )
    return {
        "primary_color": _check_hex(primary_color, "primary_color"),
        "secondary_color": _check_hex(secondary_color, "secondary_color"),
        "title_color": _check_hex(title_color, "title_color"),
        "background_color": _check_hex(background_color, "background_color"),
        "font_family": font_family,
        "title_zone": title,
        "brand_zone": brand,
        "canvas_width_px": canvas_width_px,
        "canvas_height_px": canvas_height_px,
    }


def check_readability(
    spec: dict[str, Any],
    *,
    title_text: str,
    title_font_size_px: float,
) -> dict[str, Any]:
    """Run the 200px readability gate over a pinned spec.

    No image is examined here; the report states that plainly.
    """
    if not title_text or not isinstance(title_text, str):
        raise CapabilityError(
            "design.cover_family: title_text must be a non-empty string"
        )
    if not isinstance(title_font_size_px, (int, float)) \
            or isinstance(title_font_size_px, bool) \
            or float(title_font_size_px) <= 0:
        raise CapabilityError(
            "design.cover_family: title_font_size_px must be positive"
        )
    canvas_width = spec["canvas_width_px"]
    scaled = float(title_font_size_px) * THUMBNAIL_WIDTH_PX / canvas_width
    ratio = contrast_ratio(spec["title_color"], spec["background_color"])
    checks = {
        "scaled_title_size": {
            "pass": scaled >= MIN_SCALED_TITLE_PX,
            "value_px_at_200": round(scaled, 2),
            "threshold_px_at_200": MIN_SCALED_TITLE_PX,
            "detail": "title font size projected to a 200px-wide thumbnail",
        },
        "contrast": {
            "pass": ratio >= MIN_CONTRAST_RATIO,
            "value": round(ratio, 2),
            "threshold": MIN_CONTRAST_RATIO,
            "detail": "title colour against background colour",
        },
    }
    verdict = "pass" if all(c["pass"] for c in checks.values()) else "fail"
    return {
        "verdict": verdict,
        "title_text": title_text,
        "scaled_title_px_at_200": round(scaled, 2),
        "contrast_ratio": round(ratio, 2),
        "checks": checks,
        "visual_proof": False,
        "method": "Arithmetic projection only: title size scaled by "
                  "200 / canvas width, plus exact colour contrast. "
                  "No rendered thumbnail image was examined.",
        "limitation": "This gate does NOT prove the title reads clearly "
                      "on a real thumbnail: a busy photo behind the words, "
                      "a thin font weight, or bad line wrapping can still "
                      "break legibility that this projection cannot see. "
                      "Do not report this as 'the thumbnail was viewed'.",
    }


def thumbnail_legibility_check(
    spec: dict[str, Any],
    *,
    title_text: str,
    title_font_size_px: float,
    image_path: Any = None,
) -> dict[str, Any]:
    """Readability gate plus, when an image is given, a weak zone signal.

    With an image, the title zone is cropped from a 200px-wide
    downscale and its tonal variation is reported. A flat, blank
    zone fails; a varied zone only passes as 'not blank'. That is
    still not a reading test, and the report says so in both cases.
    """
    report = check_readability(
        spec, title_text=title_text,
        title_font_size_px=title_font_size_px)
    if image_path is None:
        report["image_check"] = {
            "performed": False,
            "reason": "no rendered image was supplied",
        }
        return report
    try:
        from PIL import Image, ImageStat
    except Exception as exc:  # pragma: no cover - Pillow is present in hevi
        raise CapabilityError(
            f"design.cover_family: Pillow required for image check: {exc}"
        ) from exc
    path = Path(image_path)
    if not path.exists():
        raise CapabilityError(
            f"design.cover_family: image not found: {image_path}"
        )
    with Image.open(path) as image:
        thumb = image.convert("L").resize(
            (THUMBNAIL_WIDTH_PX,
             max(1, round(image.height * THUMBNAIL_WIDTH_PX / image.width))))
        zone = spec["title_zone"]
        box = (
            int(zone["x"] * thumb.width),
            int(zone["y"] * thumb.height),
            int((zone["x"] + zone["w"]) * thumb.width),
            int((zone["y"] + zone["h"]) * thumb.height),
        )
        crop = thumb.crop(box)
        stat = ImageStat.Stat(crop)
        variation = float(stat.stddev[0]) if stat.stddev else 0.0
    report["image_check"] = {
        "performed": True,
        "title_zone_stddev_at_200px": round(variation, 2),
        "not_blank": variation > 1.0,
        "note": "Tonal variation only: a non-blank zone is necessary "
                "for legibility, not sufficient. This still does not "
                "prove the title can be read.",
    }
    return report


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
             aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    spec = define_cover_spec(
        primary_color=params["primary_color"],
        secondary_color=params["secondary_color"],
        title_color=params["title_color"],
        background_color=params["background_color"],
        font_family=params["font_family"],
        title_zone=params["title_zone"],
        brand_zone=params["brand_zone"],
        canvas_width_px=int(params.get("canvas_width_px", 1080)),
        canvas_height_px=int(params.get("canvas_height_px", 1920)),
    )
    report = thumbnail_legibility_check(
        spec,
        title_text=str(params["title_text"]),
        title_font_size_px=float(params["title_font_size_px"]),
        image_path=params.get("image_path"),
    )
    report["spec"] = spec
    report_path = out_dir / "cover_family_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"],
            "visual_proof": False},
    )


def register_cover_family_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="design.cover_family",
            kind="line",
            aspects=["9:16", "16:9"],
            params_schema={
                "type": "object",
                "properties": {
                    "primary_color": {"type": "string"},
                    "secondary_color": {"type": "string"},
                    "title_color": {"type": "string"},
                    "background_color": {"type": "string"},
                    "font_family": {"type": "string"},
                    "title_zone": {"type": "object"},
                    "brand_zone": {"type": "object"},
                    "canvas_width_px": {"type": "integer", "minimum": 1},
                    "canvas_height_px": {"type": "integer", "minimum": 1},
                    "title_text": {"type": "string"},
                    "title_font_size_px": {"type": "number",
                                           "exclusiveMinimum": 0},
                    "image_path": {"type": "string"},
                },
                "required": ["primary_color", "secondary_color",
                             "title_color", "background_color",
                             "font_family", "title_zone", "brand_zone",
                             "title_text", "title_font_size_px"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            description=(
                "Cover family spec: fixed primary/secondary colours, "
                "headline font, title zone and brand-mark zone, with "
                "zone overlap and frame checks, plus a 200px "
                "readability gate (scaled title size and contrast "
                "thresholds). Without a rendered image the gate is an "
                "arithmetic projection and is reported as such, never "
                "as a viewed thumbnail."
            ),
            line="design",
            has_media_output=False,
        )
    )
    return ["design.cover_family"]


register_cover_family_capabilities_once()
