"""Register the brandfilm line as a Hevi capability.

This makes the CPU 15s brand-film line invocable by name from any product line:

    from hevi.capabilities import get
    cap = get("brandfilm.line")
    result = cap.render(
        {"brand_name": "Hevi 视频工厂", "selling_points": [...], "aspect": "16:9"},
        out_dir="output/brandfilm/dt-16-9",
        duration=15.0, aspect="16:9", seed=42,
    )
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityError,
    CapabilityResult,
    register,
)
from hevi.brandfilm.pipeline import BrandfilmBrief, run_brandfilm_pipeline


_PARAMS_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "brand_name": {"type": "string", "minLength": 1},
        "selling_points": {"type": "array", "items": {"type": "string"}},
        "logo": {"type": ["string", "null"]},
        "product_images": {"type": "array", "items": {"type": "string"}},
        "aspect": {"type": "string", "enum": ["16:9", "9:16"]},
        "bpm": {"type": "number"},
        "fps": {"type": "integer"},
    },
    "required": ["brand_name", "selling_points"],
}


def _render_brandfilm(
    params: dict[str, Any],
    out_dir: str,
    *,
    duration: float = 15.0,
    aspect: str = "16:9",
    seed: int = 42,
) -> CapabilityResult:
    aspect = params.get("aspect", aspect)
    if aspect not in ("16:9", "9:16"):
        raise CapabilityError(f"unsupported aspect: {aspect}")

    brief = BrandfilmBrief(
        brand_name=params["brand_name"],
        selling_points=list(params.get("selling_points", [])),
        logo=params.get("logo"),
        product_images=list(params.get("product_images", []) or []),
        aspect=aspect,
        duration=float(params.get("duration", duration)),
        bpm=float(params.get("bpm", 120.0)),
        seed=int(params.get("seed", seed)),
        fps=int(params.get("fps", 30)),
        output_dir=out_dir,
    )
    manifest = run_brandfilm_pipeline(brief)
    qg = manifest.get("quality_gates", {})
    if not qg.get("all_passed", False):
        raise CapabilityError(
            f"brandfilm gates failed: {[k for k, v in qg.items() if isinstance(v, dict) and v.get('returncode') != 0]}"
        )
    outs = manifest.get("outputs", {})
    return CapabilityResult(
        mp4=outs.get("final_mp4"),
        png=manifest.get("outputs", {}).get("cover"),
        wav=outs.get("score_wav"),
        duration_s=manifest.get("ffprobe", {}).get("duration_s", 0.0) or 0.0,
        sha256=manifest.get("sha256", ""),
        qa=qg,
    )


def register_brandfilm_capability() -> Capability:
    cap = Capability(
        name="brandfilm.line",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema=_PARAMS_SCHEMA,
        cpu_cost_hint=12.0,  # ~12 CPU-seconds per video-second on 20-core CPU
        render=_render_brandfilm,
    )
    register(cap)
    return cap


# Auto-register on import so product lines can call get("brandfilm.line") directly.
register_brandfilm_capability()
