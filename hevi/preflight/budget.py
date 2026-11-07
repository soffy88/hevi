"""preflight.budget —— 成本预估＋预算门。

计价口径（2026-10-24 实测）：
- Flow credits：月度 1000（硬上限）＋每日 50（当日先用赠额，非硬上限）。
  因此预算门语义：超月度剩余 → FAIL；超当日剩余 → WARN（动用月度池，
  不是拦住）；这与 2026-10-24 当天实花 80 credits（>50）一致——
  当日赠额不是硬 cap，写成硬 cap 会把真实发生的生成误拦。
- PixStag 按秒 USD 计价，本地无台账 → 只 INFO，须人工确认账户余额。
- SVI-Film 本地 GPU：credits 为 0，成本为 GPU 机时（未定价）→ INFO。

台账复用 stickman.CreditsLedger 的口径：接受任何带
monthly_remaining / daily_remaining 属性（或同名字典键）的对象；
传 None 表示无台账 → WARN（无法核预算），不 FAIL。
"""

from __future__ import annotations

import math
from typing import Any

from hevi.preflight.beats import get_model_spec
from hevi.preflight.findings import Finding


def estimate_cost(
    model: str, duration_s: float, clip_count: int = 1
) -> dict[str, Any]:
    spec = get_model_spec(model)
    if spec.currency == "credits" and spec.window_s and spec.credits_per_clip is not None:
        clips = clip_count * max(1, math.ceil(duration_s / spec.window_s))
        return {
            "model": model,
            "clips": clips,
            "amount": clips * spec.credits_per_clip,
            "currency": "credits",
            "note": spec.note,
        }
    if spec.currency == "USD" and spec.usd_per_s is not None:
        return {
            "model": model,
            "clips": clip_count,
            "amount": round(duration_s * clip_count * spec.usd_per_s, 4),
            "currency": "USD",
            "note": spec.note,
        }
    return {
        "model": model,
        "clips": clip_count,
        "amount": None,
        "currency": spec.currency,
        "note": spec.note,
    }


def _remaining(ledger: Any, key: str) -> int | None:
    if ledger is None:
        return None
    if isinstance(ledger, dict):
        value = ledger.get(key)
    else:
        value = getattr(ledger, key, None)
    return int(value) if value is not None else None


def budget_gate(
    estimate: dict[str, Any], ledger: Any = None, beat_id: str = ""
) -> list[Finding]:
    if estimate["currency"] == "USD":
        return [Finding(
            "INFO", "budget_usd_manual",
            f"预估 ${estimate['amount']}（{estimate['clips']} 条 × "
            f"{estimate['note']}）：本地无 PixStag 台账，须人工确认账户余额",
            beat_id=beat_id, detail=estimate,
        )]
    if estimate["currency"] == "local-gpu":
        return [Finding(
            "INFO", "budget_local_gpu",
            "本地 GPU 生成：credits 为 0，成本为 GPU 机时（未定价）",
            beat_id=beat_id, detail=estimate,
        )]

    amount = int(estimate["amount"] or 0)
    monthly = _remaining(ledger, "monthly_remaining")
    daily = _remaining(ledger, "daily_remaining")
    if monthly is None or daily is None:
        return [Finding(
            "WARN", "budget_no_ledger",
            f"预估 {amount} credits，但无台账可核：无法确认月度／当日余额",
            beat_id=beat_id, detail=estimate,
        )]
    if amount > monthly:
        return [Finding(
            "FAIL", "budget_monthly_exceeded",
            f"预估 {amount} credits 超月度剩余 {monthly}：拦住",
            beat_id=beat_id, detail={**estimate, "monthly_remaining": monthly},
        )]
    if amount > daily:
        return [Finding(
            "WARN", "budget_daily_grant_exceeded",
            f"预估 {amount} credits 超当日赠额剩余 {daily}：将动用月度池（月度剩余 {monthly}）",
            beat_id=beat_id, detail={**estimate, "daily_remaining": daily},
        )]
    return [Finding(
        "INFO", "budget_ok",
        f"预估 {amount} credits：当日剩余 {daily}，月度剩余 {monthly}",
        beat_id=beat_id, detail=estimate,
    )]
