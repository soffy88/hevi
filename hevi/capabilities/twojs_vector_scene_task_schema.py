"""Two.js vector scene task schema (``video.twojs_vector_scene_task_schema``).

Contract-only schema for one Two.js-style vector scene
task: its id and the scene graph it carries. Clean-room
restatement of the jonobr1/two.js method (see
``ANIMATION_STUDIO_18_ATTRIBUTION.md``); no upstream code
appears in this schema.

This module is a **contract layer only**. The schema never
renders, scores, or calls a model; ``compile`` returns a
contract declaring ``executed_here: false`` and
``output_file: None`` on a well-formed task, and raises
``CapabilityError`` on any shape violation. Real execution
needs a separate Two.js runtime and is a separate work item.
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
from hevi.capabilities.twojs_vector_scene_gate import (
    check_twojs_vector_scene,
)

_Registered = False

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string", "minLength": 1},
        "scene": {"type": "object"},
    },
    "required": ["task_id", "scene"],
    "additionalProperties": False,
}


def compile_twojs_vector_scene_task(task: Any) -> dict[str, Any]:
    """Compile one Two.js vector scene task contract.

    Returns a contract declaring ``executed_here: false``
    and ``output_file: None`` on a well-formed task.
    Raises :class:`CapabilityError` on any shape violation.
    The contract certifies the shape of the task only; it
    renders nothing and executes nothing.
    """
    if not isinstance(task, dict):
        raise CapabilityError("twojs_vector_scene_task: task must be a JSON object")
    for key in SCHEMA["required"]:
        if key not in task:
            raise CapabilityError(f"twojs_vector_scene_task: missing required field {key!r}")
    extra = sorted(set(task) - set(SCHEMA["properties"]))
    if extra:
        raise CapabilityError("twojs_vector_scene_task: unknown fields: " + ", ".join(extra))
    verdict = check_twojs_vector_scene(task["scene"])
    if verdict["verdict"] != "pass":
        first = verdict["issues"][0]
        raise CapabilityError(f"twojs_vector_scene_task: {first['code']}: {first['detail']}")
    return {
        "contract": "twojs-vector-scene-task",
        "task_id": task["task_id"],
        "backend": task["scene"]["backend"],
        "layer_count": len(task["scene"]["layers"]),
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_twojs_vector_scene_task(params.get("task"))
    contract_path = out_dir / "twojs_vector_scene_task_contract.json"
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


def register_twojs_vector_scene_task_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.twojs_vector_scene_task_schema",
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
                "Two.js vector scene task contract (fake): task id and a "
                "scene graph passing the Two.js vector scene gate; shape "
                "only, never executed here."
            ),
        )
    )
    return ["video.twojs_vector_scene_task_schema"]


__all__ = [
    "SCHEMA",
    "compile_twojs_vector_scene_task",
    "register_twojs_vector_scene_task_schema_capabilities_once",
]
