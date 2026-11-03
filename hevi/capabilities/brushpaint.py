"""Brush painting capability (procedural, zero-cost image route).

Registers one ``hevi.capabilities`` entry:

* ``image.brush_scene`` — paint a stylised brush-stroke scene from a
  JSON scene spec (or a bundled template) with the clean-room engine in
  ``hevi.image.brushpaint``.  Two outputs: a finished (or partial, via
  ``progress``) still PNG, or a short MP4 of the painting painting
  itself, stroke by stroke, with a living sway tail.  Fully local CPU
  work: no keys, no network, deterministic per (spec, seed) -- this is
  the zero-cost image provider the storyfilm line can route to
  (``preset=brush`` / ``image_provider="brush"``).

Registration note: this module registers itself on import (guarded,
idempotent), following the ``shot.recipe_cards`` precedent.
``hevi/capabilities/__init__.py`` is intentionally NOT edited here
because that file carries unrelated uncommitted work; once that lands,
move the import there and drop the import-time call.
"""

from __future__ import annotations

import json
import time
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

_ASPECT_SIZE = {"9:16": (720, 1280), "16:9": (1280, 720), "1:1": (960, 960)}


def _render_brush_scene(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.image.brushpaint import (
        SpecError,
        build_strokes,
        get_template,
        list_templates,
        parse_scene,
        render_paint_video,
        render_still,
    )

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mode = str(params.get("mode", "still"))
    try:
        spec = params.get("scene")
        if spec is None:
            template = str(params.get("template", "pond_night"))
            spec = get_template(template)
        else:
            template = str(spec.get("name", "custom"))
        if params.get("seed") is not None:
            spec = {**spec, "seed": int(params["seed"])}
        elif seed:
            spec = {**spec, "seed": int(seed)}
        scene = parse_scene(spec)
    except SpecError as exc:
        raise CapabilityError(f"image.brush_scene: {exc}") from exc
    except Exception as exc:
        raise CapabilityError(f"image.brush_scene: {exc}") from exc

    width, height = _ASPECT_SIZE.get(aspect, (720, 1280))
    (out_dir / "brush_scene.json").write_text(
        json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    started = time.perf_counter()
    strokes = build_strokes(scene, width, height)

    if mode == "still":
        progress = float(params.get("progress", 1.0))
        img = render_still(scene, width, height, progress=progress)
        png_path = out_dir / "brush_scene.png"
        img.save(png_path)
        return CapabilityResult(
            png=str(png_path),
            sha256=compute_sha256(png_path),
            qa={
                "mode": "still",
                "template": template,
                "templates_available": list_templates(),
                "size": f"{width}x{height}",
                "progress": progress,
                "stroke_count": len(strokes),
                "render_seconds": round(time.perf_counter() - started, 2),
                "cost": 0.0,
                "note": (
                    "Procedural brush-stroke painting (seeded field "
                    "sampling, local CPU). Stylised storybook look; not "
                    "photorealistic and draws scenes, not characters."
                ),
            },
        )

    if mode == "paint":
        seconds = float(params.get("paint_seconds", 0.0) or 0.0)
        if seconds <= 0:
            seconds = float(duration) if duration and duration > 0 else 20.0
        seconds = min(120.0, max(2.0, seconds))
        mp4_path = out_dir / "brush_scene.mp4"
        stats = render_paint_video(
            scene, mp4_path, width, height, seconds=seconds, fps=12
        )
        return CapabilityResult(
            mp4=str(mp4_path),
            duration_s=stats["seconds"],
            sha256=compute_sha256(mp4_path),
            qa={
                "mode": "paint",
                "template": template,
                "templates_available": list_templates(),
                "size": f"{width}x{height}",
                "stroke_count": stats["strokes"],
                "sway_strokes": stats["sway_strokes"],
                "frames": stats["frames"],
                "render_seconds": stats["render_seconds"],
                "cost": 0.0,
                "note": (
                    "Stroke-by-stroke painting video with a swaying "
                    "hold tail. Procedural and deterministic; stylised "
                    "storybook look, not photorealistic."
                ),
            },
        )

    raise CapabilityError(f"image.brush_scene: unknown mode {mode!r} (want still|paint)")


def register_brushpaint_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="image.brush_scene",
            kind="shot",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "template": {
                        "type": "string",
                        "default": "pond_night",
                        "description": "Bundled scene template (pond_night / meadow_dawn / river_dusk / village_night); ignored when 'scene' is given",
                    },
                    "scene": {
                        "type": "object",
                        "description": "Full scene spec: {name, seed, step, background, layers:[{type, ...params}]}; layer types: swirl_sky, moon, stars, hills, water, cypress, tree, house, meadow, clouds",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["still", "paint"],
                        "default": "still",
                        "description": "still = PNG at 'progress'; paint = MP4 of the painting painting itself",
                    },
                    "progress": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "default": 1.0,
                        "description": "Still mode only: reveal progress (1 = finished painting)",
                    },
                    "paint_seconds": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 120,
                        "default": 0,
                        "description": "Paint mode only: clip length; 0 = use the call duration or 20 s",
                    },
                    "seed": {
                        "type": "integer",
                        "description": "Override the scene seed (deterministic per seed)",
                    },
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.35,
            render=_render_brush_scene,
            description=(
                "Procedural brush-stroke scene painter (clean-room hevi "
                "engine): layered field primitives -> thousands of seeded "
                "brush strokes -> still PNG or stroke-by-stroke paint MP4. "
                "Zero cost, offline, deterministic. Stylised storybook "
                "landscapes/backgrounds; not photorealistic, no characters."
            ),
            line="image",
        )
    )
    return ["image.brush_scene"]


# Import-time registration (see module docstring for why this is not
# wired through hevi/capabilities/__init__.py yet).
register_brushpaint_capabilities_once()
