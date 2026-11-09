"""Cost gate: show the plan and the estimated price before rendering.

The gate lists the model/provider, aspect, resolution, duration, audio and the
credit estimate, and refuses a render that would cross the per-episode cap.
Prices are planning estimates, not vendor quotes (see ``credits.py``).
"""

from __future__ import annotations

from typing import Any

from .credits import CreditLedger, budget_cap, price_for
from .schema import iter_shots

CREDITS_PER_CNY = 100.0  # one credit is displayed as ¥0.01


def _seconds(storyboard: dict[str, Any]) -> float:
    return round(sum(float(s.get("duration_s") or 0) for s in iter_shots(storyboard)), 3)


def build_plan(
    storyboard: dict[str, Any],
    script: dict[str, Any] | None = None,
    *,
    provider: str = "offline",
    model: str = "",
    aspect: str = "9:16",
    resolution: str = "1080x1920",
    audio: str = "piper+mixtrack",
    ledger: CreditLedger | None = None,
) -> dict[str, Any]:
    shots = list(iter_shots(storyboard))
    segments = storyboard.get("segments") or []
    seconds = _seconds(storyboard)
    price = price_for(provider, seconds)
    cny = float(price.get("estimated_cny") or 0.0)
    credits = round(cny * CREDITS_PER_CNY)
    cap = ledger.cap if ledger is not None else budget_cap()
    spent = ledger.spent() if ledger is not None else 0.0
    remaining = round(max(0.0, cap - spent), 4)
    return {
        "provider": provider,
        "model": model or provider,
        "aspect": aspect,
        "resolution": resolution,
        "duration_s": seconds,
        "audio": audio,
        "segments": len(segments),
        "shots": len(shots),
        "per_second_cny": price.get("per_second_cny", 0.0),
        "price_status": price.get("price_status"),
        "estimated_cny": round(cny, 4),
        "credits_estimate": credits,
        "credits_unit": "1 credit = ¥0.01 (display only)",
        "budget_cap_cny": round(cap, 4),
        "spent_cny": round(spent, 4),
        "remaining_cny": remaining,
        "first_segment_only": True,
        "note": "先只出第 1 段；三项自检通过后再出其余。价格是计划估算，不是供应商报价。",
    }


def gate(plan: dict[str, Any], *, ledger: CreditLedger | None = None) -> dict[str, Any]:
    estimated = float(plan.get("estimated_cny") or 0.0)
    remaining = float(plan.get("remaining_cny") or 0.0) if ledger is None else ledger.remaining()
    allowed = estimated <= remaining + 1e-9
    return {
        "allowed": allowed,
        "estimated_cny": estimated,
        "remaining_cny": round(remaining, 4),
        "reason": "" if allowed else f"预算不足：预计 {estimated:.2f} 元 > 剩余 {remaining:.2f} 元",
    }


def approve_plan(
    plan: dict[str, Any],
    *,
    ledger: CreditLedger | None = None,
    approved: bool | None = None,
) -> dict[str, Any]:
    """Return the plan plus the gate verdict; an explicit refusal is respected."""
    verdict = gate(plan, ledger=ledger)
    if approved is False:
        verdict.update({"allowed": False, "reason": verdict.get("reason") or "用户取消"})
    return {**plan, "gate": verdict}
