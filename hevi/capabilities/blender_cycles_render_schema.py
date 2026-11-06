"""Blender Cycles render schema (``video.blender_cycles_render_schema``).

Fake-level contract for a Blender Cycles render of the kind
described in the ChrisHKAI-Video creator-intro review (see
``CHRISHKAI_VIDEO_ATTRIBUTION.md``): Blender 5.2 or newer,
Node 22 or newer, Python 3.9 or newer, ffmpeg, headless
Chrome, and a GPU — the reviewed method requires one, chosen
from OptiX, CUDA, HIP, oneAPI or Metal — with samples and
scale. The contract certifies the shape of the plan only. It
renders nothing: any plan claiming a render ran here fails
outright. Every compiled contract declares
``executed_here: false``, and real rendering on a GPU is a
separate case.
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

# GPU backends the reviewed device selection covers.
DEVICES: tuple[str, ...] = ("OptiX", "CUDA", "HIP", "oneAPI", "Metal")


def compile_blender_cycles_render(plan: Any) -> dict[str, Any]:
    """Compile one Blender Cycles render contract.

    ``plan`` carries the tool prerequisites (``blender``,
    ``node``, ``python``, ``ffmpeg``, ``headless_chrome``),
    ``gpu_required``, ``device``, ``samples`` and ``scale``.
    Raises :class:`CapabilityError` on any shape violation,
    on a missing prerequisite, on a GPU not being required,
    on an unknown device, or on any claim that a render ran
    here. The returned contract records that nothing was
    executed here.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("Blender Cycles render plan must be an object")
    if plan.get("executed_here") is True or plan.get("rendered_here") is True:
        raise CapabilityError("render claims are refused here; this contract executes nothing")
    for field in ("blender", "node", "python"):
        value = plan.get(field)
        if not isinstance(value, str) or not value:
            raise CapabilityError(f"Blender Cycles render plan requires {field} version")
    for field in ("ffmpeg", "headless_chrome"):
        if plan.get(field) is not True:
            raise CapabilityError(f"Blender Cycles render plan requires {field}")
    if plan.get("gpu_required") is not True:
        raise CapabilityError(
            "the reviewed method requires a GPU; a CPU-only render plan is refused"
        )
    device = plan.get("device")
    if device not in DEVICES:
        raise CapabilityError(
            "Blender Cycles render device must be one of OptiX, CUDA, HIP, oneAPI, Metal"
        )
    samples = plan.get("samples")
    if not isinstance(samples, int) or isinstance(samples, bool) or samples <= 0:
        raise CapabilityError("Blender Cycles render samples must be a positive integer")
    scale = plan.get("scale")
    if not isinstance(scale, (int, float)) or isinstance(scale, bool):
        raise CapabilityError("Blender Cycles render scale must be a number")
    if scale <= 0 or scale > 1:
        raise CapabilityError("Blender Cycles render scale must be in (0, 1]")
    return {
        "contract": "blender-cycles-render",
        "blender": plan["blender"],
        "node": plan["node"],
        "python": plan["python"],
        "ffmpeg": True,
        "headless_chrome": True,
        "gpu_required": True,
        "device": device,
        "samples": samples,
        "scale": scale,
        "executed_here": False,
        "rendered_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = compile_blender_cycles_render(params.get("plan"))
    report_path = out_dir / "blender_cycles_render_contract.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "device": report["device"],
            "executed_here": False,
        },
    )


def register_blender_cycles_render_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.blender_cycles_render_schema",
            kind="video",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {"type": "object"},
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="obase",
            description=(
                "Blender Cycles render contract (fake): Blender 5.2+, "
                "Node 22+, Python 3.9+, ffmpeg, headless Chrome, GPU "
                "required, OptiX/CUDA/HIP/oneAPI/Metal; no render."
            ),
        )
    )
    return ["video.blender_cycles_render_schema"]


__all__ = [
    "DEVICES",
    "compile_blender_cycles_render",
    "register_blender_cycles_render_schema_capabilities_once",
]
