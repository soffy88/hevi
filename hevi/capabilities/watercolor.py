"""Procedural watercolour as a first-class capability (``image.watercolor_render``).

Wraps :mod:`hevi.watercolor` (midpoint-displacement polygons stacked
in ~40 near-transparent layers) so handdraw scenes, HyperFrames
compositions and any other line can call it by name for backgrounds
and elements instead of paying for an AI image or shipping a flat
vector look.

Fully local / offline / $0: pure Python + Pillow, no model, no
network, no API key.  Deterministic — the same seed (the render
``seed`` argument, or ``params["seed"]`` when given) and the same
parameters produce a byte-identical PNG.

Failure semantics follow the contract: invalid params are rejected
by ``render_safe`` schema validation, and any core ``ValueError``
(wrong shape, bad colour, oversized displacement, ...) is re-raised
as :class:`CapabilityError` — never a fake success.
"""

from __future__ import annotations

import json
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

_COLOR_SCHEMA: dict[str, Any] = {
    "anyOf": [
        {"type": "string", "minLength": 1, "description": "#RRGGBB (or #RGB)"},
        {
            "type": "array",
            "items": {"type": "integer", "minimum": 0, "maximum": 255},
            "minItems": 3,
            "maxItems": 3,
        },
    ]
}

_POINT_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {"type": "number"},
    "minItems": 2,
    "maxItems": 2,
}

_SHAPE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "enum": ["circle", "ellipse", "rect", "polygon", "path"],
            "description": "Shape kind; polygon/path need >=3 points, rect needs 2 corners",
        },
        "color": _COLOR_SCHEMA,
        "center": _POINT_SCHEMA,
        "radius": {"type": "number", "exclusiveMinimum": 0},
        "rx": {"type": "number", "exclusiveMinimum": 0},
        "ry": {"type": "number", "exclusiveMinimum": 0},
        "points": {
            "type": "array",
            "items": _POINT_SCHEMA,
            "minItems": 2,
            "description": "Polygon/path vertices (>=3) or rect corners (2)",
        },
        "layers": {"type": "integer", "minimum": 1, "maximum": 200},
        "alpha": {"type": "number", "exclusiveMinimum": 0, "maximum": 1.0},
        "displacement": {"type": "number", "minimum": 0, "maximum": 64},
        "iterations": {"type": "integer", "minimum": 0, "maximum": 6},
    },
    "required": ["type", "color"],
    "additionalProperties": False,
}


def _render_watercolor(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.watercolor import demo_scene_shapes, render_flat_image, render_watercolor_image

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    width = int(params.get("width", 640))
    height = int(params.get("height", 480))
    background = params.get("background", "#FFFEF8")
    layers = params.get("layers", 40)
    alpha = params.get("alpha", 0.045)
    displacement = params.get("displacement", 6.0)
    iterations = params.get("iterations", 4)
    effective_seed = int(params["seed"]) if "seed" in params else int(seed)
    flat = bool(params.get("flat", False))
    preset = params.get("scene_preset")

    shapes = params.get("shapes")
    if not shapes:
        if preset == "sun_mountain_lake":
            shapes = demo_scene_shapes(width, height)
        else:
            raise CapabilityError(
                "image.watercolor_render: provide params.shapes or "
                "params.scene_preset='sun_mountain_lake'"
            )

    try:
        if flat:
            img = render_flat_image(
                shapes, width=width, height=height, background=background
            )
        else:
            img = render_watercolor_image(
                shapes,
                width=width,
                height=height,
                background=background,
                layers=layers,
                alpha=alpha,
                displacement=displacement,
                iterations=iterations,
                seed=effective_seed,
            )
    except ValueError as exc:
        raise CapabilityError(f"image.watercolor_render: {exc}") from exc
    except Exception as exc:
        raise CapabilityError(f"image.watercolor_render failed: {exc}") from exc

    png_path = out_dir / "watercolor.png"
    img.save(png_path, format="PNG")
    sidecar = {
        "capability": "image.watercolor_render",
        "seed": effective_seed,
        "width": width,
        "height": height,
        "background": background,
        "layers": layers,
        "alpha": alpha,
        "displacement": displacement,
        "iterations": iterations,
        "flat": flat,
        "scene_preset": preset,
        "shape_count": len(shapes),
        "cost_usd": 0.0,
        "deterministic": True,
    }
    (out_dir / "watercolor_sidecar.json").write_text(
        json.dumps(sidecar, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return CapabilityResult(
        png=str(png_path),
        duration_s=0.0,
        sha256=compute_sha256(png_path),
        qa={
            "seed": effective_seed,
            "layers": layers,
            "alpha": alpha,
            "displacement": displacement,
            "iterations": iterations,
            "flat": flat,
            "shape_count": len(shapes),
            "scene_preset": preset,
            "cost_usd": 0.0,
            "deterministic": True,
            "sidecar": str(out_dir / "watercolor_sidecar.json"),
        },
    )


def register_watercolor_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True

    register(
        Capability(
            name="image.watercolor_render",
            kind="shot",
            aspects=["16:9", "9:16", "1:1", "4:3", "3:4"],
            params_schema={
                "type": "object",
                "properties": {
                    "shapes": {
                        "type": "array",
                        "items": _SHAPE_SCHEMA,
                        "minItems": 1,
                        "description": "Shapes to paint, in back-to-front order; "
                        "either shapes or scene_preset is required",
                    },
                    "scene_preset": {
                        "type": "string",
                        "enum": ["sun_mountain_lake"],
                        "description": "Built-in demo composition used when shapes is omitted",
                    },
                    "width": {"type": "integer", "minimum": 16, "maximum": 2048, "default": 640},
                    "height": {"type": "integer", "minimum": 16, "maximum": 2048, "default": 480},
                    "background": _COLOR_SCHEMA,
                    "layers": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 200,
                        "default": 40,
                        "description": "Stacked displaced copies per shape; more layers = deeper centre saturation",
                    },
                    "alpha": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                        "maximum": 1.0,
                        "default": 0.045,
                        "description": "Opacity of each layer (0.045 ~= 4.5%); centre accumulates ~layers x alpha, edges only a few layers",
                    },
                    "displacement": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 64,
                        "default": 6.0,
                        "description": "Midpoint-displacement amplitude in px for the first iteration (decays x0.58 per iteration)",
                    },
                    "iterations": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 6,
                        "default": 4,
                        "description": "Midpoint-displacement rounds; each round doubles the outline points",
                    },
                    "seed": {
                        "type": "integer",
                        "description": "Optional seed override; defaults to the render seed argument",
                    },
                    "flat": {
                        "type": "boolean",
                        "default": False,
                        "description": "True renders ordinary flat fill instead (comparison baseline)",
                    },
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.5,
            render=_render_watercolor,
            description=(
                "Procedural watercolour render (pure Python + Pillow, local, "
                "$0, no AI image generation): each shape's outline is roughened "
                "by iterated midpoint displacement and stacked in ~40 layers "
                "at ~4.5% opacity, so centres saturate while edges bleed pale. "
                "Deterministic — same seed + params give a byte-identical PNG. "
                "Params: shapes (circle/ellipse/rect/polygon/path + colour, "
                "with per-shape layers/alpha/displacement/iterations overrides) "
                "or scene_preset='sun_mountain_lake'; layers (default 40), "
                "alpha per layer (default 0.045), displacement px (default 6), "
                "iterations (default 4), width/height/background, flat=true "
                "for a flat-fill comparison render. Use for handdraw / "
                "HyperFrames backgrounds and scene elements."
            ),
            line="watercolor",
        )
    )
    return ["image.watercolor_render"]
