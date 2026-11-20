"""Adaptive execution planner gate (``qa.freevideo_execution_planner_gate``).

A FreeVideo-style low-VRAM run never loads weights before it
has a plan: every request re-measures the VRAM and host
budgets, fixes how many of the 50 transformer blocks stay
resident, how many sit in pinned host memory, and when disk
streaming takes over. The residency rule, in the reviewer's
own words, is: resident blocks are the smaller of the blocks
the VRAM budget can hold after the activation working set
(each block 432.5 MB) and 44, never fewer than 8; pinned
host memory is capped at 22 GiB; two prefetch slots open at
a VRAM budget of 14 GiB or more, one slot below that; an
out-of-memory failure retries at most twice, first by
lightening the placement, then by shrinking the compute
chunks, and only last by staging attention outputs in host
memory. The plan must be printed dry (``plan`` before any
weight is loaded) — plan-before-run.

Clean-room restatement of the FlashML-org/FreeVideo method
(see ``FREEVIDEO_ATTRIBUTION.md``); no upstream code appears
here. This gate judges plan descriptions only; it never runs
FreeVideo, loads weights, or touches a GPU. Real execution
needs a separate Python 3.12 + FreeVideo runtime environment
and is a separate work item.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

BLOCK_MB = 432.5
MAX_RESIDENT_BLOCKS = 44
MIN_RESIDENT_BLOCKS = 8
PINNED_HOST_CAP_GIB = 22.0
TWO_SLOT_VRAM_GIB = 14.0
MAX_OOM_RETRIES = 2
QUALITY_LEVELS: frozenset[str] = frozenset({"Light", "Medium", "High", "Max"})


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_freevideo_execution_plan(plan: Any) -> dict[str, Any]:
    """Validate a FreeVideo-style adaptive execution plan.

    Verdicts are ``pass`` / ``fail`` only. A plan fails when
    a required field is missing or mistyped, when the
    resident block count is outside 8..44 or disagrees with
    the residency formula for a stated activation working
    set, when pinned host memory exceeds 22 GiB, when disk
    streaming is not declared although the non-resident
    blocks plus host working memory exceed the host budget,
    when the prefetch slot count disagrees with the VRAM
    budget, when OOM retries exceed two, when the quality
    level is unknown, or when the plan was not printed dry
    before loading weights.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(plan, dict):
        return fail("plan_not_object", "execution plan must be a JSON object")
    for field in (
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
    ):
        if field not in plan:
            return fail("plan_field_missing", f"execution plan must carry {field!r}")
    vram = plan["vram_gib"]
    ram = plan["ram_gib"]
    if not _is_number(vram) or vram <= 0:
        return fail("vram_budget_invalid", "vram_gib must be a positive number")
    if not _is_number(ram) or ram <= 0:
        return fail("ram_budget_invalid", "ram_gib must be a positive number")
    resident = plan["resident_blocks"]
    if not isinstance(resident, int) or isinstance(resident, bool):
        return fail("resident_blocks_not_int", "resident_blocks must be an integer")
    if resident < MIN_RESIDENT_BLOCKS or resident > MAX_RESIDENT_BLOCKS:
        return fail(
            "resident_blocks_out_of_range",
            f"resident_blocks must be {MIN_RESIDENT_BLOCKS}..{MAX_RESIDENT_BLOCKS}, got {resident}",
        )
    activation = plan.get("activation_working_set_gib")
    if activation is not None:
        if not _is_number(activation) or activation < 0:
            return fail(
                "activation_working_set_invalid",
                "activation_working_set_gib must be a non-negative number",
            )
        expected = min(
            math.floor((vram - activation) * 1024 / BLOCK_MB),
            MAX_RESIDENT_BLOCKS,
        )
        expected = max(expected, MIN_RESIDENT_BLOCKS)
        if resident != expected:
            return fail(
                "resident_blocks_formula_mismatch",
                f"resident_blocks must be {expected} for vram_gib {vram} and "
                f"activation_working_set_gib {activation}, got {resident}",
            )
    pinned = plan.get("pinned_host_gib")
    if pinned is not None:
        if not _is_number(pinned) or pinned < 0:
            return fail("pinned_host_invalid", "pinned_host_gib must be a non-negative number")
        if pinned > PINNED_HOST_CAP_GIB:
            return fail(
                "pinned_host_over_cap",
                f"pinned_host_gib must not exceed {PINNED_HOST_CAP_GIB}, got {pinned}",
            )
    non_resident = plan.get("non_resident_gib")
    host_working = plan.get("host_working_gib")
    if (
        non_resident is not None
        and host_working is not None
        and _is_number(non_resident)
        and _is_number(host_working)
        and non_resident + host_working > ram
        and plan.get("disk_streaming") is not True
    ):
        return fail(
            "disk_streaming_required",
            "non-resident blocks plus host working memory exceed the host "
            "budget, so disk_streaming must be declared true",
        )
    slots = plan["prefetch_slots"]
    if not isinstance(slots, int) or isinstance(slots, bool):
        return fail("prefetch_slots_not_int", "prefetch_slots must be an integer")
    expected_slots = 2 if vram >= TWO_SLOT_VRAM_GIB else 1
    if slots != expected_slots:
        return fail(
            "prefetch_slots_mismatch",
            f"prefetch_slots must be {expected_slots} for vram_gib {vram}, got {slots}",
        )
    retries = plan["oom_retries"]
    if not isinstance(retries, int) or isinstance(retries, bool):
        return fail("oom_retries_not_int", "oom_retries must be an integer")
    if retries < 0 or retries > MAX_OOM_RETRIES:
        return fail(
            "oom_retries_over_limit",
            f"oom_retries must be 0..{MAX_OOM_RETRIES}, got {retries}",
        )
    if plan["quality"] not in QUALITY_LEVELS:
        return fail(
            "quality_unknown",
            f"quality must be one of Light, Medium, High, Max, got {plan['quality']!r}",
        )
    for field in ("seconds", "width", "height"):
        if not _is_number(plan[field]) or plan[field] <= 0:
            return fail(f"{field}_invalid", f"{field} must be a positive number")
    if plan["plan_dry_run"] is not True:
        return fail(
            "plan_dry_run_required",
            "the plan must be printed dry (plan_before_run) before any weight is loaded",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_freevideo_execution_plan(params.get("plan"))
    report_path = out_dir / "freevideo_execution_plan_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_freevideo_execution_planner_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.freevideo_execution_planner_gate",
            kind="line",
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
            layer="oskill",
            description=(
                "FreeVideo adaptive execution planner gate: resident "
                "blocks 8..44 by the VRAM formula, pinned host capped "
                "at 22 GiB, disk streaming declared when the host "
                "budget is exceeded, prefetch slots by VRAM, OOM "
                "retries at most two, plan printed dry first."
            ),
        )
    )
    return ["qa.freevideo_execution_planner_gate"]


__all__ = [
    "BLOCK_MB",
    "MAX_OOM_RETRIES",
    "MAX_RESIDENT_BLOCKS",
    "MIN_RESIDENT_BLOCKS",
    "PINNED_HOST_CAP_GIB",
    "QUALITY_LEVELS",
    "TWO_SLOT_VRAM_GIB",
    "check_freevideo_execution_plan",
    "register_freevideo_execution_planner_gate_capabilities_once",
]
