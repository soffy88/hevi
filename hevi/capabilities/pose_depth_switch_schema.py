"""Depth switch contract schema (``video.pose_depth_switch_schema``).

Contract-only schema for one pose-gallery white/depth
switch: its id, pose key, view, mode, and the two paths.
Clean-room restatement of the anhao/ai-pose-gallery-zh
depth-map method (see ``AI_POSE_GALLERY_ZH_ATTRIBUTION.md``);
no upstream code, image, or data appears in this schema.

This module is a **contract layer only**. The schema never
renders, scores, or calls a model; ``compile`` returns a
contract declaring ``executed_here: false`` and
``output_file: None`` on a well-formed switch, and raises
``CapabilityError`` on any shape violation. The contract
certifies the declaration shape and the derived depth path
only; it does not check the files on disk (that is the
``qa.pose_depth_switch_gate`` with disk checking on).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.pose_depth_switch_gate import check_pose_depth_switch
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "switch_id": {"type": "string", "minLength": 1},
        "pose_key": {"type": "string", "minLength": 1},
        "view": {"type": "string"},
        "mode": {"type": "string"},
        "white_path": {"type": "string"},
        "depth_path": {"type": "string"},
        "home": {"type": "string"},
    },
    "required": ["switch_id", "pose_key", "view", "mode"],
    "additionalProperties": False,
}


def compile_pose_depth_switch(switch: Any) -> dict[str, Any]:
    """Compile one depth switch contract.

    Returns a contract declaring ``executed_here: false``
    and ``output_file: None`` on a well-formed switch.
    Raises :class:`CapabilityError` on any shape violation.
    The contract certifies the shape of the switch only;
    it touches no file on disk.
    """
    if not isinstance(switch, dict):
        raise CapabilityError("pose_depth_switch: switch must be a JSON object")
    for key in SCHEMA["required"]:
        if key not in switch:
            raise CapabilityError(f"pose_depth_switch: missing required field {key!r}")
    extra = sorted(set(switch) - set(SCHEMA["properties"]))
    if extra:
        raise CapabilityError("pose_depth_switch: unknown fields: " + ", ".join(extra))
    verdict = check_pose_depth_switch(switch, check_disk=False)
    if verdict["verdict"] != "pass":
        first = verdict["issues"][0]
        raise CapabilityError(f"pose_depth_switch: {first['code']}: {first['detail']}")
    return {
        "contract": "pose-depth-switch",
        "switch_id": switch["switch_id"],
        "pose_key": switch["pose_key"],
        "view": switch["view"],
        "mode": switch["mode"],
        "white_path": verdict["white_path"],
        "depth_path": verdict["depth_path"],
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_pose_depth_switch(params.get("switch"))
    contract_path = out_dir / "pose_depth_switch_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={
            "report_json": str(contract_path),
            "switch_id": contract["switch_id"],
            "executed_here": False,
        },
    )


def register_pose_depth_switch_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.pose_depth_switch_schema",
            kind="video",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "switch": {"type": "object"},
                },
                "required": ["switch"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="obase",
            line="video",
            description=(
                "Pose-gallery depth switch contract (fake): pose key, "
                "view, white/depth mode, derived depth path; shape "
                "only, never executed here, files not touched."
            ),
        )
    )
    return ["video.pose_depth_switch_schema"]


__all__ = [
    "SCHEMA",
    "compile_pose_depth_switch",
    "register_pose_depth_switch_schema_capabilities_once",
]
