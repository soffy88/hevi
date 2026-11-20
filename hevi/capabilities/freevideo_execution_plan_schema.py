"""FreeVideo execution plan schema (``video.freevideo_execution_plan_schema``).

Contract-only schema for one FreeVideo-style adaptive
execution plan: its id, the measured budgets, the resident
block count, the prefetch slots, the OOM retry budget, and
the dry-run declaration. Clean-room restatement of the
FlashML-org/FreeVideo method (see
``FREEVIDEO_ATTRIBUTION.md``); no upstream code appears in
this schema.

This module is a **contract layer only**. The schema never
renders, scores, or calls a model; ``compile`` returns a
contract declaring ``executed_here: false`` and
``output_file: None`` on a well-formed plan, and raises
``CapabilityError`` on any shape violation. Real execution
needs a separate Python 3.12 + FreeVideo runtime
environment and is a separate work item.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.freevideo_execution_planner_gate import (
    check_freevideo_execution_plan,
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
        "plan_id": {"type": "string", "minLength": 1},
        "vram_gib": {"type": "number"},
        "ram_gib": {"type": "number"},
        "resident_blocks": {"type": "integer"},
        "prefetch_slots": {"type": "integer"},
        "oom_retries": {"type": "integer"},
        "plan_dry_run": {"type": "boolean"},
        "quality": {"type": "string"},
        "seconds": {"type": "number"},
        "width": {"type": "number"},
        "height": {"type": "number"},
        "pinned_host_gib": {"type": "number"},
        "disk_streaming": {"type": "boolean"},
        "activation_working_set_gib": {"type": "number"},
        "non_resident_gib": {"type": "number"},
        "host_working_gib": {"type": "number"},
    },
    "required": [
        "plan_id",
        "vram_gib",
        "ram_gib",
        "resident_blocks",
        "prefetch_slots",
        "oom_retries",
        "plan_dry_run",
        "quality",
        "seconds",
        "width",
        "height",
    ],
    "additionalProperties": False,
}


def compile_freevideo_execution_plan(plan: Any) -> dict[str, Any]:
    """Compile one FreeVideo execution plan contract.

    Returns a contract declaring ``executed_here: false``
    and ``output_file: None`` on a well-formed plan.
    Raises :class:`CapabilityError` on any shape violation.
    The contract certifies the shape of the plan only; it
    renders nothing and executes nothing.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("freevideo_execution_plan: plan must be a JSON object")
    for key in SCHEMA["required"]:
        if key not in plan:
            raise CapabilityError(f"freevideo_execution_plan: missing required field {key!r}")
    extra = sorted(set(plan) - set(SCHEMA["properties"]))
    if extra:
        raise CapabilityError("freevideo_execution_plan: unknown fields: " + ", ".join(extra))
    verdict = check_freevideo_execution_plan(plan)
    if verdict["verdict"] != "pass":
        first = verdict["issues"][0]
        raise CapabilityError(f"freevideo_execution_plan: {first['code']}: {first['detail']}")
    return {
        "contract": "freevideo-execution-plan",
        "plan_id": plan["plan_id"],
        "resident_blocks": plan["resident_blocks"],
        "prefetch_slots": plan["prefetch_slots"],
        "disk_streaming": plan.get("disk_streaming", False),
        "quality": plan["quality"],
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_freevideo_execution_plan(params.get("plan"))
    contract_path = out_dir / "freevideo_execution_plan_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={
            "report_json": str(contract_path),
            "plan_id": contract["plan_id"],
            "executed_here": False,
        },
    )


def register_freevideo_execution_plan_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.freevideo_execution_plan_schema",
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
                "FreeVideo execution plan contract (fake): budgets, "
                "resident blocks, prefetch slots, OOM retries, and "
                "the dry-run declaration; shape only, never executed here."
            ),
        )
    )
    return ["video.freevideo_execution_plan_schema"]


__all__ = [
    "SCHEMA",
    "compile_freevideo_execution_plan",
    "register_freevideo_execution_plan_schema_capabilities_once",
]
