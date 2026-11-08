"""Seedance task contract (``video.seedance_task_schema``).

Fake-level contract for a Seedance generation task of
the kind described in the Eian workflow review (see
``EIAN_WORKFLOW_ATTRIBUTION.md``): one of the two checked
model ids, pricing stated on the official per-million-token
basis, 720p generation upscaled to 1080p afterwards, and
asynchronous task polling. The contract certifies the
shape of the plan only. It submits nothing, calls no API,
and holds no key: any plan carrying a key, or claiming a
task was submitted or ran here, fails outright. Every
compiled contract declares ``executed_here: false``, and
real submission is a separate keyed case.
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

MODELS: dict[str, int] = {
    "doubao-seedance-2-5-260628": 70,
    "doubao-seedance-2-0-mini-260615": 23,
}
PRICING_UNIT = "cny_per_million_tokens"
POLL_SHAPE = "GET tasks/{id}"


def compile_seedance_task(plan: Any) -> dict[str, Any]:
    """Compile one Seedance task contract.

    ``plan`` carries ``model``, ``pricing`` (unit and rate),
    ``resolution``, ``upscale_to`` and ``task`` (polling
    shape). Raises :class:`CapabilityError` on any shape
    violation, on an unknown model, on pricing that is not
    the official per-million-token basis with the checked
    rate, on any embedded key, or on any claim that a task
    was submitted or ran here. The returned contract
    records that nothing was executed here.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("Seedance task plan must be an object")
    if plan.get("executed_here") is True or plan.get("submitted") is True:
        raise CapabilityError(
            "task submission claims are refused here; this contract executes nothing"
        )
    for key in ("api_key", "ark_api_key", "ARK_API_KEY"):
        if key in plan:
            raise CapabilityError(
                "keys are never embedded in a task plan; the key stays in the environment"
            )
    model = plan.get("model")
    if model not in MODELS:
        raise CapabilityError("Seedance task contract covers the two checked model ids only")
    pricing = plan.get("pricing")
    if not isinstance(pricing, dict):
        raise CapabilityError("Seedance task plan requires pricing on the token basis")
    if pricing.get("unit") != PRICING_UNIT:
        raise CapabilityError("Seedance pricing must be per million tokens; the bill governs")
    if pricing.get("rate") != MODELS[model]:
        raise CapabilityError(f"checked rate for {model} is {MODELS[model]} CNY per million tokens")
    if plan.get("resolution") != "720p":
        raise CapabilityError("Seedance task contract generates at 720p")
    if plan.get("upscale_to") != "1080p":
        raise CapabilityError("720p generation must upscale to 1080p afterwards")
    task = plan.get("task")
    if not isinstance(task, dict):
        raise CapabilityError("Seedance task plan requires a task shape")
    if task.get("polling") != POLL_SHAPE:
        raise CapabilityError("Seedance task polling is GET tasks/{id}")
    return {
        "contract": "seedance-task",
        "model": model,
        "pricing": {
            "unit": PRICING_UNIT,
            "rate": MODELS[model],
        },
        "resolution": "720p",
        "upscale_to": "1080p",
        "polling": POLL_SHAPE,
        "executed_here": False,
        "submitted": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = compile_seedance_task(params.get("plan"))
    report_path = out_dir / "seedance_task_contract.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "model": report["model"],
            "executed_here": False,
        },
    )


def register_seedance_task_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.seedance_task_schema",
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
                "Seedance task contract (fake): checked model id, "
                "official per-million-token pricing, 720p generation "
                "upscaled to 1080p, task polling; no key, no submission."
            ),
        )
    )
    return ["video.seedance_task_schema"]


__all__ = [
    "MODELS",
    "POLL_SHAPE",
    "PRICING_UNIT",
    "compile_seedance_task",
    "register_seedance_task_schema_capabilities_once",
]
