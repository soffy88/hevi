"""Capability contract integration for RISO B-roll templates (CAPABILITY_CONTRACT.md).

Registers all 10 templates into hevi.capabilities.registry under `riso.<template>`
with kind="overlay" (or "shot") and aspect="9:16".
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityError,
    CapabilityResult,
    compute_sha256,
    register,
)
from hevi.riso.constants import TEMPLATE_NAMES
from hevi.riso.gatekeeper import validate_screen_content
from hevi.riso.render import render_clip

# JSON Schemas for the 10 templates
SCHEMAS: dict[str, dict[str, Any]] = {
    "versus": {
        "type": "object",
        "properties": {
            "myth": {"type": "string"},
            "reality": {"type": "string"},
            "tag": {"type": "string"},
            "palette": {"type": "string"},
        },
        "required": ["myth", "reality"],
    },
    "title": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "subtitle": {"type": "string"},
            "number": {"type": "string"},
            "tag": {"type": "string"},
            "palette": {"type": "string"},
        },
        "required": ["title"],
    },
    "number": {
        "type": "object",
        "properties": {
            "context": {"type": "string"},
            "number": {"type": "string"},
            "unit": {"type": "string"},
            "insight": {"type": "string"},
            "palette": {"type": "string"},
        },
        "required": ["number"],
    },
    "compare": {
        "type": "object",
        "properties": {
            "val_a": {"type": "number"},
            "val_b": {"type": "number"},
            "label_a": {"type": "string"},
            "label_b": {"type": "string"},
            "disp_a": {"type": "string"},
            "disp_b": {"type": "string"},
            "caption": {"type": "string"},
            "palette": {"type": "string"},
        },
        "required": ["val_a", "val_b"],
    },
    "converge": {
        "type": "object",
        "properties": {
            "inputs": {"type": "array", "items": {"type": "string"}},
            "core": {"type": "string"},
            "tag": {"type": "string"},
            "palette": {"type": "string"},
        },
        "required": ["core"],
    },
    "network": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "hub": {"type": "string"},
            "nodes": {"type": "array", "items": {"type": "string"}},
            "insight": {"type": "string"},
            "palette": {"type": "string"},
        },
        "required": ["hub"],
    },
    "focus": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "options": {"type": "array", "items": {"type": "string"}},
            "selected_index": {"type": "integer"},
            "reason": {"type": "string"},
            "palette": {"type": "string"},
        },
        "required": ["options", "selected_index"],
    },
    "steps": {
        "type": "object",
        "properties": {
            "steps": {"type": "array", "items": {"type": "string"}},
            "active_step": {"type": "integer"},
            "palette": {"type": "string"},
        },
        "required": ["steps"],
    },
    "shot": {
        "type": "object",
        "properties": {
            "image_url": {"type": "string"},
            "caption": {"type": "string"},
            "tag": {"type": "string"},
            "palette": {"type": "string"},
        },
        "required": ["caption"],
    },
    "quote": {
        "type": "object",
        "properties": {
            "quote": {"type": "string"},
            "author": {"type": "string"},
            "palette": {"type": "string"},
        },
        "required": ["quote"],
    },
}


def _make_renderer(template_name: str):
    def render(
        params: dict[str, Any],
        out_dir: Path | str,
        *,
        duration: float = 3.0,
        aspect: str = "9:16",
        seed: int = 42,
    ) -> CapabilityResult:
        if aspect != "9:16":
            raise CapabilityError(f"RISO templates currently support aspect '9:16', got '{aspect}'")

        out_path = Path(out_dir).resolve()
        out_path.mkdir(parents=True, exist_ok=True)
        clip_id = f"riso_{template_name}_{uuid.uuid4().hex[:6]}"

        palette_key = params.get("palette", "ink_blue_neon_pink")

        # Validate schema
        schema = SCHEMAS.get(template_name, {})
        required = schema.get("required", [])
        for req in required:
            if req not in params:
                raise CapabilityError(f"Missing required parameter '{req}' for template {template_name}")

        try:
            res = render_clip(
                template_name=template_name,
                data=params,
                out_dir=out_path,
                clip_id=clip_id,
                duration_s=duration,
                palette_key=palette_key,
                seed=seed,
                render_video=True,
            )
        except Exception as e:
            raise CapabilityError(f"Rendering failed for riso.{template_name}: {e}")

        mp4_path = res["mp4_path"]
        if not mp4_path or not mp4_path.exists():
            raise CapabilityError(f"Output MP4 missing after render: {mp4_path}")

        sha = compute_sha256(mp4_path)

        qa_info = {
            "psnr": res["psnr"],
            "palette": palette_key,
            "seed": seed,
            "keyframe_png": str(res["keyframe_png"]),
        }

        return CapabilityResult(
            duration_s=duration,
            sha256=sha,
            qa=qa_info,
            mp4=str(mp4_path),
            png=str(res["keyframe_png"]),
        )

    return render


def register_riso_capabilities() -> None:
    """Register all 10 RISO templates as capabilities."""
    for tmpl in TEMPLATE_NAMES:
        cap_name = f"riso.{tmpl}"
        kind = "shot" if tmpl == "shot" else "overlay"
        schema = SCHEMAS.get(tmpl, {"type": "object"})
        cap = Capability(
            name=cap_name,
            kind=kind,
            aspects=["9:16"],
            params_schema=schema,
            cpu_cost_hint=1.2,
            render=_make_renderer(tmpl),
        )
        register(cap, overwrite=True)
