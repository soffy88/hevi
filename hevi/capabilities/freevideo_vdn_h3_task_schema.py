"""FreeVideo VDN-H3 generation task schema (``video.freevideo_vdn_h3_task_schema``).

Contract-only schema for one VDN-H3 generation task: its
id, the pinned distilled model identity, the quality tier,
the two-pass flag, the first and last frames, and the
references. Clean-room restatement of the
FlashML-org/FreeVideo method (see
``FREEVIDEO_ATTRIBUTION.md``); no upstream code appears in
this schema. The task names the distilled model explicitly:
VDN-H3 is an 8-step distilled derivative, never the
original H3.

This module is a **contract layer only**. The schema never
renders, scores, or calls a model; ``compile`` returns a
contract declaring ``executed_here: false`` and
``output_file: None`` on a well-formed task, and raises
``CapabilityError`` on any shape violation. Real execution
needs a separate Python 3.12 + FreeVideo runtime
environment and is a separate work item.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.freevideo_execution_planner_gate import QUALITY_LEVELS
from hevi.capabilities.freevideo_vdn_h3_distinction_gate import (
    check_freevideo_vdn_h3_identity,
)
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
        "task_id": {"type": "string", "minLength": 1},
        "model_name": {"type": "string", "minLength": 1},
        "model_kind": {"type": "string", "minLength": 1},
        "revision": {"type": "string", "minLength": 1},
        "steps": {"type": "integer"},
        "quality": {"type": "string"},
        "seconds": {"type": "number"},
        "width": {"type": "number"},
        "height": {"type": "number"},
        "first_frame": {"type": "string"},
        "last_frame": {"type": "string"},
        "references": {"type": "array"},
        "two_pass": {"type": "boolean"},
    },
    "required": [
        "task_id",
        "model_name",
        "model_kind",
        "revision",
        "steps",
        "quality",
        "seconds",
        "width",
        "height",
    ],
    "additionalProperties": False,
}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def compile_freevideo_vdn_h3_task(task: Any) -> dict[str, Any]:
    """Compile one FreeVideo VDN-H3 generation task contract.

    Returns a contract declaring ``executed_here: false``
    and ``output_file: None`` on a well-formed task.
    Raises :class:`CapabilityError` on any shape violation.
    The contract certifies the shape of the task only; it
    renders nothing and executes nothing.
    """
    if not isinstance(task, dict):
        raise CapabilityError("freevideo_vdn_h3_task: task must be a JSON object")
    for key in SCHEMA["required"]:
        if key not in task:
            raise CapabilityError(f"freevideo_vdn_h3_task: missing required field {key!r}")
    extra = sorted(set(task) - set(SCHEMA["properties"]))
    if extra:
        raise CapabilityError("freevideo_vdn_h3_task: unknown fields: " + ", ".join(extra))
    verdict = check_freevideo_vdn_h3_identity(
        {
            "model_name": task["model_name"],
            "model_kind": task["model_kind"],
            "revision": task["revision"],
            "steps": task["steps"],
        }
    )
    if verdict["verdict"] != "pass":
        first = verdict["issues"][0]
        raise CapabilityError(f"freevideo_vdn_h3_task: {first['code']}: {first['detail']}")
    if task["quality"] not in QUALITY_LEVELS:
        raise CapabilityError(
            "freevideo_vdn_h3_task: quality must be one of Light, Medium, High, Max, "
            f"got {task['quality']!r}"
        )
    for field in ("seconds", "width", "height"):
        if not _is_number(task[field]) or task[field] <= 0:
            raise CapabilityError(f"freevideo_vdn_h3_task: {field} must be a positive number")
    return {
        "contract": "freevideo-vdn-h3-task",
        "task_id": task["task_id"],
        "model_name": task["model_name"],
        "revision": task["revision"],
        "quality": task["quality"],
        "two_pass": task.get("two_pass", False),
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_freevideo_vdn_h3_task(params.get("task"))
    contract_path = out_dir / "freevideo_vdn_h3_task_contract.json"
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


def register_freevideo_vdn_h3_task_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.freevideo_vdn_h3_task_schema",
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
                "FreeVideo VDN-H3 generation task contract (fake): "
                "pinned distilled model identity, quality tier, "
                "two-pass flag, first and last frames, references; "
                "shape only, never executed here."
            ),
        )
    )
    return ["video.freevideo_vdn_h3_task_schema"]


__all__ = [
    "SCHEMA",
    "compile_freevideo_vdn_h3_task",
    "register_freevideo_vdn_h3_task_schema_capabilities_once",
]
