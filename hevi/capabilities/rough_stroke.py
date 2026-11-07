"""``image.rough_stroke`` capability: rough-style hand-drawn strokes.

Thin registry wrapper around the clean-room technique module
:mod:`hevi.layer4_legacy.handdraw.rough_stroke`.  It takes caller-supplied
polylines (polygons, sampled curves, lettering outlines, ...), roughens
them deterministically from the render ``seed`` and writes a transparent
PNG plus a ``rough.svg`` carrying the same geometry as SVG paths.

CPU-only, no paid calls.  Fails closed with ``CapabilityError`` on any
invalid input instead of returning a fabricated success.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityError,
    CapabilityResult,
    register,
)

logger = logging.getLogger(__name__)

_Registered = False

_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["polylines"],
    "properties": {
        "polylines": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "array",
                "minItems": 2,
                "items": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 2,
                    "items": {"type": "number"},
                },
            },
            "description": "One or more polylines, each a list of [x, y] points.",
        },
        "closed": {"type": "boolean", "default": False},
        "roughness": {"type": "number", "minimum": 0, "maximum": 50, "default": 1.0},
        "bowing": {"type": "number", "minimum": 0, "maximum": 50, "default": 1.0},
        "double_stroke": {"type": "boolean", "default": True},
        "stroke_width": {"type": "number", "minimum": 0.5, "maximum": 20, "default": 3.0},
        "canvas_width": {"type": "integer", "minimum": 16, "maximum": 4096, "default": 640},
        "canvas_height": {"type": "integer", "minimum": 16, "maximum": 4096, "default": 640},
    },
}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _render_rough_stroke(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from PIL import Image, ImageDraw

    from hevi.layer4_legacy.handdraw.rough_stroke import roughen_polylines

    params = params or {}
    try:
        results = roughen_polylines(
            params.get("polylines"),
            roughness=params.get("roughness", 1.0),
            bowing=params.get("bowing", 1.0),
            seed=int(seed),
            double_stroke=bool(params.get("double_stroke", True)),
            closed=bool(params.get("closed", False)),
        )
    except (ValueError, TypeError) as exc:
        raise CapabilityError(f"image.rough_stroke: {exc}") from exc

    width = int(params.get("canvas_width", 640))
    height = int(params.get("canvas_height", 640))
    stroke_width = float(params.get("stroke_width", 3.0))
    if width <= 0 or height <= 0 or stroke_width <= 0:
        raise CapabilityError("image.rough_stroke: canvas/stroke sizes must be positive")
    closed = bool(params.get("closed", False))

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    ink = (24, 24, 24, 255)
    line_width = max(1, round(stroke_width))
    for result in results:
        for one_pass in result.passes:
            line = list(one_pass)
            if closed and line:
                line.append(line[0])
            if len(line) >= 2:
                draw.line(line, fill=ink, width=line_width, joint="curve")
    png_path = out_dir / "rough_stroke.png"
    image.save(png_path)

    svg_paths = [path for result in results for path in result.svg_paths]
    svg_body = "\n".join(
        f'<path d="{d}" fill="none" stroke="#181818" '
        f'stroke-width="{stroke_width}" stroke-linecap="round" stroke-linejoin="round"/>'
        for d in svg_paths
    )
    svg_path = out_dir / "rough.svg"
    svg_path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">\n{svg_body}\n</svg>\n',
        encoding="utf-8",
    )
    sidecar = out_dir / "rough_stroke.json"
    sidecar.write_text(
        json.dumps(
            {
                "stroke_style": "rough",
                "seed": int(seed),
                "closed": closed,
                "svg_paths": svg_paths,
                "passes_per_polyline": [len(r.passes) for r in results],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if not png_path.is_file() or not svg_path.is_file():
        raise CapabilityError("image.rough_stroke: render incomplete")
    return CapabilityResult(
        png=str(png_path),
        duration_s=0.0,
        sha256=_sha256_file(png_path),
        qa={
            "stroke_style": "rough",
            "svg": str(svg_path),
            "sidecar": str(sidecar),
            "svg_paths": svg_paths,
            "polylines": len(results),
            "passes_per_polyline": [len(r.passes) for r in results],
            "seed": int(seed),
        },
    )


def register_rough_stroke_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="image.rough_stroke",
            kind="shot",
            aspects=["16:9", "9:16", "1:1"],
            params_schema=_PARAMS_SCHEMA,
            cpu_cost_hint=0.2,
            render=_render_rough_stroke,
            description=(
                "Rough-style hand-drawn strokes (clean-room Python technique): "
                "jitters polyline vertices (roughness), bows segment midpoints "
                "(bowing) and double-draws each path, deterministically from "
                "the render seed. Writes a transparent PNG plus rough.svg. "
                "Also available inside the handdraw line via stroke_style='rough'."
            ),
            line="handdraw",
        )
    )
    logger.info("registered image.rough_stroke capability")
    return ["image.rough_stroke"]
