"""FreeVideo post-chain task schema (``video.freevideo_post_chain_task_schema``).

Contract-only schema for one FreeVideo post-chain task: its
id, the licensed post steps, and the output. Clean-room
restatement of the FlashML-org/FreeVideo method (see
``FREEVIDEO_ATTRIBUTION.md``); no upstream code appears in
this schema. Each step carries its license tag so the
non-commercial and research-only steps can never be pooled
with the commercial ones.

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
from hevi.capabilities.freevideo_post_chain_license_gate import (
    check_freevideo_post_chain,
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
        "steps": {"type": "array"},
        "output": {"type": "string", "minLength": 1},
    },
    "required": ["task_id", "steps", "output"],
    "additionalProperties": False,
}


def compile_freevideo_post_chain_task(task: Any) -> dict[str, Any]:
    """Compile one FreeVideo post-chain task contract.

    Returns a contract declaring ``executed_here: false``
    and ``output_file: None`` on a well-formed task.
    Raises :class:`CapabilityError` on any shape violation.
    The contract certifies the shape of the task only; it
    renders nothing and executes nothing.
    """
    if not isinstance(task, dict):
        raise CapabilityError("freevideo_post_chain_task: task must be a JSON object")
    for key in SCHEMA["required"]:
        if key not in task:
            raise CapabilityError(f"freevideo_post_chain_task: missing required field {key!r}")
    extra = sorted(set(task) - set(SCHEMA["properties"]))
    if extra:
        raise CapabilityError("freevideo_post_chain_task: unknown fields: " + ", ".join(extra))
    verdict = check_freevideo_post_chain(task["steps"])
    if verdict["verdict"] != "pass":
        first = verdict["issues"][0]
        raise CapabilityError(f"freevideo_post_chain_task: {first['code']}: {first['detail']}")
    return {
        "contract": "freevideo-post-chain-task",
        "task_id": task["task_id"],
        "step_count": len(task["steps"]),
        "licenses": [step["license"] for step in task["steps"]],
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_freevideo_post_chain_task(params.get("task"))
    contract_path = out_dir / "freevideo_post_chain_task_contract.json"
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


def register_freevideo_post_chain_task_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.freevideo_post_chain_task_schema",
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
                "FreeVideo post-chain task contract (fake): licensed "
                "post steps with license tags, output; shape only, "
                "never executed here."
            ),
        )
    )
    return ["video.freevideo_post_chain_task_schema"]


__all__ = [
    "SCHEMA",
    "compile_freevideo_post_chain_task",
    "register_freevideo_post_chain_task_schema_capabilities_once",
]
