"""Xiaoya half-body lipsync schema (``video.xiaoya_halfbody_lipsync_schema``).

Fake-level contract for one half-body lipsync run: the engine,
the model files it loads, the frame rate it renders at, and
the measured correlation it records. The contract certifies
the shape of the plan only. It runs no model, loads no weight
file, and renders nothing: every compiled contract declares
``executed_here: false`` and ``output_file: None``. A
placeholder card is not a lipsync run and is refused here.

Clean-room restatement of the lipsync run described in the
``live-parity`` branch checkout (see
``DIGITAL_HOST_IMPROVEMENT_ATTRIBUTION.md``).
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

ENGINE = "wav2lip_onnx_cpu"
MODEL_FILES: tuple[str, ...] = ("wav2lip_gan_96", "yoloface_8n", "silero_vad_v6")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def compile_xiaoya_halfbody_lipsync(plan: Any) -> dict[str, Any]:
    """Compile one half-body lipsync contract.

    ``plan`` carries ``engine`` (wav2lip_onnx_cpu),
    ``model_files`` (all three files declared present),
    ``fps`` (a positive integer), ``realtime_factor`` (a
    number at least 1 when present), ``lipsync_corr`` (a
    positive number when present), and ``uses_placeholder_card``
    (which must be false). Raises :class:`CapabilityError` on
    any shape violation or on a placeholder card. The returned
    contract records that nothing was executed here.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("xiaoya lipsync plan must be an object")
    if plan.get("executed_here") is True:
        raise CapabilityError("lipsync claims are refused here; this contract runs nothing")
    if plan.get("engine") != ENGINE:
        raise CapabilityError("only the measured wav2lip_onnx_cpu engine is accepted")
    model_files = plan.get("model_files")
    if not isinstance(model_files, dict) or any(
        model_files.get(name) is not True for name in MODEL_FILES
    ):
        raise CapabilityError(
            "all three model files must be declared present: "
            "wav2lip_gan_96, yoloface_8n, silero_vad_v6"
        )
    fps = plan.get("fps")
    if not isinstance(fps, int) or isinstance(fps, bool) or fps <= 0:
        raise CapabilityError("fps must be a positive integer")
    realtime_factor = plan.get("realtime_factor")
    if realtime_factor is not None and (not _is_number(realtime_factor) or realtime_factor < 1.0):
        raise CapabilityError("realtime_factor must be at least 1 when present")
    corr = plan.get("lipsync_corr")
    if corr is not None and (not _is_number(corr) or corr <= 0):
        raise CapabilityError("lipsync_corr must be a positive number when present")
    if plan.get("uses_placeholder_card") is True:
        raise CapabilityError("a placeholder card is not a lipsync run")
    return {
        "contract": "xiaoya-halfbody-lipsync",
        "engine": ENGINE,
        "model_files": sorted(MODEL_FILES),
        "fps": fps,
        "realtime_factor": realtime_factor,
        "lipsync_corr": corr,
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_xiaoya_halfbody_lipsync(params.get("plan"))
    contract_path = out_dir / "xiaoya_halfbody_lipsync_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={
            "report_json": str(contract_path),
            "engine": contract["engine"],
            "executed_here": False,
        },
    )


def register_xiaoya_halfbody_lipsync_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.xiaoya_halfbody_lipsync_schema",
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
            line="video",
            description=(
                "xiaoya half-body lipsync contract (fake): Wav2Lip "
                "ONNX CPU engine, three model files, fps, realtime "
                "factor, correlation; shape only, never executed here."
            ),
        )
    )
    return ["video.xiaoya_halfbody_lipsync_schema"]


__all__ = [
    "ENGINE",
    "MODEL_FILES",
    "compile_xiaoya_halfbody_lipsync",
    "register_xiaoya_halfbody_lipsync_schema_capabilities_once",
]
