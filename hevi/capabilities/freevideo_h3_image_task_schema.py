"""FreeVideo H3 Image task schema (``video.freevideo_h3_image_task_schema``).

Contract-only schema for one H3 Image task: its id, the
image model, the resolution in megapixels (at most 16), and
the license acknowledgement. Clean-room restatement of the
FlashML-org/FreeVideo method (see
``FREEVIDEO_ATTRIBUTION.md``); no upstream code appears in
this schema. The Qwen image path is research-only and must
be declared so; the MiniMax H3 Image path runs under the
MiniMax H3 Image community license.

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
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

MAX_MEGAPIXELS = 16.0
ALLOWED_MODELS: frozenset[str] = frozenset({"minimax-h3-image", "qwen-image-2.1"})

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string", "minLength": 1},
        "model": {"type": "string"},
        "megapixels": {"type": "number"},
        "width": {"type": "number"},
        "height": {"type": "number"},
        "license_acknowledged": {"type": "boolean"},
        "research_only": {"type": "boolean"},
        "commercial": {"type": "boolean"},
    },
    "required": [
        "task_id",
        "model",
        "megapixels",
        "width",
        "height",
        "license_acknowledged",
    ],
    "additionalProperties": False,
}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def compile_freevideo_h3_image_task(task: Any) -> dict[str, Any]:
    """Compile one FreeVideo H3 Image task contract.

    Returns a contract declaring ``executed_here: false``
    and ``output_file: None`` on a well-formed task.
    Raises :class:`CapabilityError` on any shape violation.
    The contract certifies the shape of the task only; it
    renders nothing and executes nothing.
    """
    if not isinstance(task, dict):
        raise CapabilityError("freevideo_h3_image_task: task must be a JSON object")
    for key in SCHEMA["required"]:
        if key not in task:
            raise CapabilityError(f"freevideo_h3_image_task: missing required field {key!r}")
    extra = sorted(set(task) - set(SCHEMA["properties"]))
    if extra:
        raise CapabilityError("freevideo_h3_image_task: unknown fields: " + ", ".join(extra))
    if task["model"] not in ALLOWED_MODELS:
        raise CapabilityError(
            "freevideo_h3_image_task: model must be one of "
            + ", ".join(sorted(ALLOWED_MODELS))
            + f", got {task['model']!r}"
        )
    megapixels = task["megapixels"]
    if not _is_number(megapixels) or megapixels <= 0 or megapixels > MAX_MEGAPIXELS:
        raise CapabilityError(
            "freevideo_h3_image_task: megapixels must be in "
            f"(0, {MAX_MEGAPIXELS}], got {megapixels!r}"
        )
    for field in ("width", "height"):
        if not _is_number(task[field]) or task[field] <= 0:
            raise CapabilityError(f"freevideo_h3_image_task: {field} must be a positive number")
    if task["license_acknowledged"] is not True:
        raise CapabilityError(
            "freevideo_h3_image_task: the image model license must be acknowledged"
        )
    if task["model"] == "qwen-image-2.1":
        if task.get("research_only") is not True:
            raise CapabilityError(
                "freevideo_h3_image_task: the Qwen image path is research-only "
                "and must be declared so"
            )
        if task.get("commercial") is True:
            raise CapabilityError(
                "freevideo_h3_image_task: the Qwen image path must never run commercially"
            )
    return {
        "contract": "freevideo-h3-image-task",
        "task_id": task["task_id"],
        "model": task["model"],
        "megapixels": task["megapixels"],
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_freevideo_h3_image_task(params.get("task"))
    contract_path = out_dir / "freevideo_h3_image_task_contract.json"
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


def register_freevideo_h3_image_task_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.freevideo_h3_image_task_schema",
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
                "FreeVideo H3 Image task contract (fake): image model, "
                "resolution at most 16 megapixels, license "
                "acknowledged, Qwen image path research-only; shape "
                "only, never executed here."
            ),
        )
    )
    return ["video.freevideo_h3_image_task_schema"]


__all__ = [
    "ALLOWED_MODELS",
    "MAX_MEGAPIXELS",
    "SCHEMA",
    "compile_freevideo_h3_image_task",
    "register_freevideo_h3_image_task_schema_capabilities_once",
]
