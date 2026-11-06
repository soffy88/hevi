"""Paid-generation economy gate (``qa.paid_generation_economy_gate``).

Clean-room restatement of the Eian short-film workflow
(see ``EIAN_WORKFLOW_ATTRIBUTION.md``): paid generation
is billed, so economy is a gate, not an afterthought.
Prices are checked on the official token basis verified
in the review — Seedance 2.5 at 70 CNY per million tokens
and Seedance 2.0 mini at 23 CNY per million tokens, about
3.04 times apart — never on a per-second price, and the
bill always governs. Generation runs at 720p and is
upscaled afterwards, the hardest shots are tried first,
a bad shot is cut or repaired in code before it is
re-shot, a re-shot is never the same prompt and frames
again, old segments are kept, and an unpaid balance stops
the run. This gate judges the generation plan only. It
submits nothing, calls no API, and spends nothing:
``executed_here`` is always false.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_paid_generation_economy(plan: Any) -> dict[str, Any]:
    """Validate a paid-generation plan on economy grounds.

    Verdicts are ``pass`` / ``fail`` only. A plan fails
    when its model is unknown, when its pricing is not
    stated on the official per-million-token basis with the
    checked rates, when no approved budget is declared,
    when a re-shot repeats the same prompt and frames,
    when a re-shot deletes the old segment, or when the
    balance check says stop.
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
        return fail("plan_not_object", "plan must be a JSON object")
    model = plan.get("model")
    if model not in MODELS:
        return fail(
            "unknown_model",
            "plan model must be a checked Seedance model id",
        )
    pricing = plan.get("pricing")
    if not isinstance(pricing, dict):
        return fail(
            "pricing_missing",
            "plan must state pricing on the official token basis",
        )
    if pricing.get("unit") != PRICING_UNIT:
        return fail(
            "pricing_not_token_basis",
            "pricing must be per million tokens; per-second prices "
            "are author conversions, and the bill governs",
        )
    if pricing.get("rate") != MODELS[model]:
        return fail(
            "pricing_rate_mismatch",
            f"checked rate for {model} is {MODELS[model]} CNY per million tokens",
        )
    budget = plan.get("budget")
    if not isinstance(budget, dict):
        return fail("budget_missing", "plan must declare a budget")
    if budget.get("approved") is not True:
        return fail(
            "budget_not_approved",
            "nothing is submitted without an approved budget",
        )
    resolution = plan.get("resolution")
    if resolution == "720p":
        if plan.get("upscale_to") != "1080p":
            return fail(
                "upscale_missing",
                "720p generation must upscale to 1080p afterwards",
            )
    elif resolution == "1080p":
        if (
            not isinstance(plan.get("direct_1080p_reason"), str)
            or not plan["direct_1080p_reason"].strip()
        ):
            return fail(
                "direct_1080p_unjustified",
                "direct 1080p generation needs a stated reason",
            )
    else:
        return fail(
            "resolution_unknown",
            "plan resolution must be 720p or 1080p",
        )
    if plan.get("hardest_first") is not True:
        return fail(
            "hardest_not_first",
            "the hardest shots are tried first, before the rest is submitted",
        )
    balance = plan.get("balance_check")
    if not isinstance(balance, dict):
        return fail(
            "balance_check_missing",
            "plan must carry a balance check before submitting",
        )
    if balance.get("balance_ok") is not True:
        return fail(
            "insufficient_balance_stop",
            "an unpaid balance stops the run; existing segments are cut together first",
        )
    retakes = plan.get("retakes")
    if isinstance(retakes, list):
        for position, retake in enumerate(retakes):
            if not isinstance(retake, dict):
                return fail(
                    "retake_not_object",
                    f"retake {position} must be an object",
                )
            if retake.get("changed_prompt_or_frames") is not True:
                return fail(
                    "retake_without_change",
                    f"retake {position} repeats the same prompt and "
                    "frames; fix the prompt or the frames first",
                )
            if retake.get("kept_old") is not True:
                return fail(
                    "old_segment_deleted",
                    f"retake {position} deletes the old segment; keep "
                    "every paid segment and pick later",
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
    report = check_paid_generation_economy(params.get("plan"))
    report_path = out_dir / "paid_generation_economy_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_paid_generation_economy_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.paid_generation_economy_gate",
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
                "Paid-generation economy gate: official token-basis "
                "pricing, approved budget, 720p then upscale, hardest "
                "shots first, re-shots change the prompt or frames, "
                "old segments kept, unpaid balance stops the run."
            ),
        )
    )
    return ["qa.paid_generation_economy_gate"]


__all__ = [
    "MODELS",
    "PRICING_UNIT",
    "check_paid_generation_economy",
    "register_paid_generation_economy_gate_capabilities_once",
]
