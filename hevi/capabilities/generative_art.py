"""Generative art capability (seeded flow fields + Julia fractals).

Registers one ``hevi.capabilities`` entry:

* ``image.generative_art`` — abstract generative art from a seeded
  spec via the original numpy/PIL engine in ``hevi.image.genart``.
  Two algorithms (``flowfield`` particle trails through a noise
  field; ``julia`` escape-time fractal) and two outputs: a still PNG
  (poster / cover bed / title background) or a seamlessly looping
  MP4 (intro / atmosphere bed / music-visualisation bed).  Fully
  local CPU work: no keys, no network, deterministic per
  (spec, seed) -- abstract only, it draws no narrative content.

The seeded-algorithm approach follows Anthropic's
``algorithmic-art`` skill (Apache-2.0; archived under
``~/workspace/references/algorithmic-art`` and installed in the
Claude/Codex skill dirs); the engine itself is original code.

Registration note: this module registers itself on import (guarded,
idempotent), following the ``shot.recipe_cards`` / ``image.brush_scene``
precedent.  ``hevi/capabilities/__init__.py`` is intentionally NOT
edited here because that file carries unrelated uncommitted work;
once that lands, move the import there and drop the import-time call.
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

_ASPECT_SIZE = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (960, 960)}

_SPEC_PASSTHROUGH = (
    "particle_count",
    "particle_life",
    "step_size",
    "noise_cells",
    "angle_turns",
    "trail",
    "orbit_radius",
    "max_iter",
    "exposure",
)


def _render_generative_art(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.image.genart import SpecError, parse_spec, render_still, render_video

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mode = str(params.get("mode", "still"))
    if mode not in ("still", "video"):
        raise CapabilityError(
            f"image.generative_art: unknown mode {mode!r} (want still|video)"
        )

    width, height = _ASPECT_SIZE.get(aspect, (1280, 720))
    spec_dict: dict[str, Any] = {
        "algorithm": str(params.get("algorithm", "flowfield")),
        "width": int(params.get("width", width)),
        "height": int(params.get("height", height)),
    }
    if params.get("seed") is not None:
        spec_dict["seed"] = int(params["seed"])
    elif seed:
        spec_dict["seed"] = int(seed)
    if params.get("colors") is not None:
        spec_dict["colors"] = params["colors"]
    elif params.get("palette") is not None:
        spec_dict["palette"] = params["palette"]
    if params.get("julia_c") is not None:
        spec_dict["julia_c"] = params["julia_c"]
    for key in _SPEC_PASSTHROUGH:
        if params.get(key) is not None:
            spec_dict[key] = params[key]

    try:
        spec = parse_spec(spec_dict)
    except SpecError as exc:
        raise CapabilityError(f"image.generative_art: {exc}") from exc

    (out_dir / "generative_art.json").write_text(
        json.dumps(spec_dict, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    started = time.perf_counter()

    if mode == "still":
        img, stats = render_still(spec)
        png_path = out_dir / "generative_art.png"
        img.save(png_path)
        return CapabilityResult(
            png=str(png_path),
            sha256=compute_sha256(png_path),
            qa={
                "mode": "still",
                **stats,
                "render_seconds": round(time.perf_counter() - started, 2),
                "note": (
                    "Seeded generative art (local CPU, deterministic). "
                    "Abstract flow-field/fractal visual: suited to "
                    "posters, cover beds, title and atmosphere "
                    "backgrounds; it carries no narrative content."
                ),
            },
        )

    seconds = float(params.get("seconds", 0.0) or 0.0)
    if seconds <= 0:
        seconds = float(duration) if duration and duration > 0 else 10.0
    seconds = min(60.0, max(2.0, seconds))
    fps = int(params.get("fps", 24) or 24)
    if not 8 <= fps <= 60:
        raise CapabilityError(f"image.generative_art: fps {fps} out of range [8, 60]")
    try:
        stats = render_video(spec, out_dir / "generative_art.mp4", seconds=seconds, fps=fps)
    except RuntimeError as exc:
        raise CapabilityError(f"image.generative_art: {exc}") from exc
    mp4_path = out_dir / "generative_art.mp4"
    return CapabilityResult(
        mp4=str(mp4_path),
        duration_s=stats["seconds"],
        sha256=compute_sha256(mp4_path),
        qa={
            "mode": "video",
            **stats,
            "loop": (
                "exact (static field, lifetime divides frame count)"
                if spec.algorithm == "flowfield"
                else "periodic orbit of the Julia constant"
            ),
            "render_seconds": round(time.perf_counter() - started, 2),
            "note": (
                "Seeded generative-art loop (local CPU, deterministic). "
                "Abstract visual bed for intros/atmosphere/music "
                "visualisation; it carries no narrative content."
            ),
        },
    )


def register_generative_art_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="image.generative_art",
            kind="shot",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "algorithm": {
                        "type": "string",
                        "enum": ["flowfield", "julia"],
                        "default": "flowfield",
                        "description": "flowfield = particle trails in a noise flow field; julia = escape-time fractal",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["still", "video"],
                        "default": "still",
                        "description": "still = PNG; video = seamlessly looping MP4",
                    },
                    "palette": {
                        "type": "string",
                        "default": "abyss",
                        "description": "Named palette: ember / abyss / sakura / verdant (ignored when 'colors' is given)",
                    },
                    "colors": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Custom palette: 2+ hex colours, e.g. [\"#0b1030\", \"#e85d1e\", \"#ffe8a8\"]",
                    },
                    "seed": {
                        "type": "integer",
                        "description": "Seed override (deterministic per seed)",
                    },
                    "width": {"type": "integer", "minimum": 64, "maximum": 3840},
                    "height": {"type": "integer", "minimum": 64, "maximum": 3840},
                    "particle_count": {
                        "type": "integer",
                        "minimum": 10,
                        "maximum": 20000,
                        "default": 1600,
                        "description": "flowfield only: particle count (density)",
                    },
                    "particle_life": {
                        "type": "integer",
                        "minimum": 8,
                        "maximum": 4000,
                        "default": 220,
                        "description": "flowfield only: advection steps per particle life",
                    },
                    "noise_cells": {
                        "type": "number",
                        "minimum": 0.5,
                        "maximum": 16.0,
                        "default": 3.0,
                        "description": "flowfield only: base noise cells across the width",
                    },
                    "angle_turns": {
                        "type": "number",
                        "minimum": 0.1,
                        "maximum": 6.0,
                        "default": 1.6,
                        "description": "flowfield only: field swirl strength",
                    },
                    "trail": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 512,
                        "default": 28,
                        "description": "flowfield video only: trail length in steps",
                    },
                    "julia_c": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                        "description": "julia only: constant c as [re, im]",
                    },
                    "orbit_radius": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 0.2,
                        "default": 0.012,
                        "description": "julia video only: orbit radius of c around its base value",
                    },
                    "max_iter": {
                        "type": "integer",
                        "minimum": 8,
                        "maximum": 2000,
                        "default": 90,
                        "description": "julia only: escape-time iteration cap",
                    },
                    "exposure": {
                        "type": "number",
                        "minimum": 0.1,
                        "maximum": 8.0,
                        "default": 1.15,
                    },
                    "seconds": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 60,
                        "default": 0,
                        "description": "video only: clip length; 0 = use the call duration or 10 s",
                    },
                    "fps": {
                        "type": "integer",
                        "minimum": 8,
                        "maximum": 60,
                        "default": 24,
                        "description": "video only: frames per second",
                    },
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=6.0,
            render=_render_generative_art,
            description=(
                "Seeded generative art (original numpy/PIL engine): "
                "flow-field particle trails or Julia fractals in named "
                "palettes -> still PNG or seamlessly looping MP4. "
                "Zero cost, offline, deterministic per (spec, seed). "
                "Abstract posters / cover beds / title & atmosphere "
                "backgrounds / music-visualisation beds; no narrative "
                "content, no text, no characters."
            ),
            line="image",
        )
    )
    return ["image.generative_art"]


# Import-time registration (see module docstring for why this is not
# wired through hevi/capabilities/__init__.py yet).
register_generative_art_capabilities_once()
