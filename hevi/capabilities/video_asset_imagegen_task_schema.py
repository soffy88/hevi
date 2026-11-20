"""Video asset imagegen task schema (``video.video_asset_imagegen_task_schema``).

Contract-only schema for one video asset imagegen task: its
id and the asset imagegen plan it carries. Clean-room
restatement of the补图 method of openai/codex ``imagegen``
(see ``VIDEO_SKILLS_10_ATTRIBUTION.md``); no upstream code
appears in this schema.

This module is a **contract layer only**. The schema never
renders, scores, or calls a model; ``compile`` returns a
contract declaring ``executed_here: false`` and
``output_file: None`` on a well-formed task, and raises
``CapabilityError`` on any shape violation. Real execution
needs a separate free-route image runtime and is a separate
work item.
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
from hevi.capabilities.video_asset_imagegen_gate import (
    check_video_asset_imagegen,
)

_Registered = False

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string", "minLength": 1},
        "plan": {"type": "object"},
    },
    "required": ["task_id", "plan"],
    "additionalProperties": False,
}


def compile_video_asset_imagegen_task(task: Any) -> dict[str, Any]:
    """Compile one video asset imagegen task contract.

    Returns a contract declaring ``executed_here: false``
    and ``output_file: None`` on a well-formed task.
    Raises :class:`CapabilityError` on any shape violation.
    The contract certifies the shape of the task only; it
    renders nothing and executes nothing.
    """
    if not isinstance(task, dict):
        raise CapabilityError("video_asset_imagegen_task: task must be a JSON object")
    for key in SCHEMA["required"]:
        if key not in task:
            raise CapabilityError(f"video_asset_imagegen_task: missing required field {key!r}")
    extra = sorted(set(task) - set(SCHEMA["properties"]))
    if extra:
        raise CapabilityError("video_asset_imagegen_task: unknown fields: " + ", ".join(extra))
    verdict = check_video_asset_imagegen(task["plan"])
    if verdict["verdict"] != "pass":
        first = verdict["issues"][0]
        raise CapabilityError(f"video_asset_imagegen_task: {first['code']}: {first['detail']}")
    return {
        "contract": "video-asset-imagegen-task",
        "task_id": task["task_id"],
        "asset_count": len(task["plan"]["assets"]),
        "kinds": sorted({asset["kind"] for asset in task["plan"]["assets"]}),
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_video_asset_imagegen_task(params.get("task"))
    contract_path = out_dir / "video_asset_imagegen_task_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={
            "report_json": str(contract_path),
            "task_id": contract["task_id"],
            "executed_here": False,
        },
    )


def register_video_asset_imagegen_task_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.video_asset_imagegen_task_schema",
            kind="video",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "task": {"type": "object"},
                },
                "required": ["task"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="obase",
            line="video",
            description=(
                "Video asset imagegen task contract (fake): task id and an "
                "asset imagegen plan passing the video asset imagegen gate; "
                "shape only, never executed here."
            ),
        )
    )
    return ["video.video_asset_imagegen_task_schema"]


__all__ = [
    "SCHEMA",
    "compile_video_asset_imagegen_task",
    "register_video_asset_imagegen_task_schema_capabilities_once",
]
