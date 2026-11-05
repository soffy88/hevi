"""Live gift and VIP gate (``qa.live_gift_vip_gate``).

Clean-room restatement of the cyber-xiaoya-live review (see
``CYBER_XIAOYA_ATTRIBUTION.md``): the upstream live system
batches gifts inside a window (same person, same gift merged;
a trigger of at least 4 people or 50 diamonds; at most 12
items per batch; at most 2 batches per minute), treats a
single gift above the VIP threshold (default 99 diamonds) with
a face-display template, top action priority and a 30-second
cooldown, and welcomes members once per session without
interrupting a song. This gate judges claims about such gift
handling only: batch figures, thresholds and cooldowns must be
declared, a VIP-priority claim without a threshold fails, a
member welcome must declare once-per-session and
never-interrupt-song, and any diamond-to-currency conversion
must declare its source. This gate executes nothing and touches
no payment or platform: ``executed_here`` is always false.
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

DEFAULT_VIP_THRESHOLD_DIAMONDS = 99
MAX_BATCH_ITEMS = 12
MAX_BATCHES_PER_MINUTE = 2


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def check_live_gift_vip(claim: Any) -> dict[str, Any]:
    """Validate a claim about live gift batching and VIP handling.

    Verdicts are ``pass`` / ``fail`` only. Batch window, trigger
    people and diamonds, max items per batch and max batches per
    minute must be declared within bounds; the VIP threshold and
    cooldown must be declared; a VIP-priority claim without a
    threshold fails; a member welcome must declare
    once-per-session and never-interrupt-song; a diamond
    conversion must declare its source.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(claim, dict):
        return fail(
            "claim_not_object",
            "live gift claim must be a JSON object",
        )
    window = claim.get("batch_window_seconds")
    if not _is_int(window) or window < 1 or window > 60:
        return fail(
            "batch_window_missing",
            "gift batching needs a window in seconds (1..60)",
        )
    trigger_people = claim.get("trigger_people")
    if not _is_int(trigger_people) or trigger_people < 1:
        return fail(
            "trigger_people_missing",
            "gift batching needs a trigger people count (>= 1)",
        )
    trigger_diamonds = claim.get("trigger_diamonds")
    if not _is_int(trigger_diamonds) or trigger_diamonds < 0:
        return fail(
            "trigger_diamonds_missing",
            "gift batching needs a trigger diamond count (>= 0)",
        )
    max_items = claim.get("max_items_per_batch")
    if not _is_int(max_items) or max_items < 1:
        return fail(
            "max_items_missing",
            "gift batching needs a max items per batch figure",
        )
    if max_items > MAX_BATCH_ITEMS:
        return fail(
            "max_items_out_of_range",
            "at most 12 items per gift batch",
        )
    max_per_minute = claim.get("max_batches_per_minute")
    if not _is_int(max_per_minute) or max_per_minute < 1:
        return fail(
            "max_batches_missing",
            "gift batching needs a max batches per minute figure",
        )
    if max_per_minute > MAX_BATCHES_PER_MINUTE:
        return fail(
            "max_batches_out_of_range",
            "at most 2 gift batches per minute",
        )
    threshold = claim.get("vip_threshold_diamonds")
    if not _is_int(threshold) or threshold < 1:
        return fail(
            "vip_threshold_missing",
            "VIP handling needs a threshold in diamonds (>= 1); "
            "a VIP-priority claim without a threshold fails",
        )
    cooldown = claim.get("vip_cooldown_seconds")
    if not _is_int(cooldown) or cooldown < 0:
        return fail(
            "vip_cooldown_missing",
            "VIP handling needs a cooldown in seconds (>= 0)",
        )
    if claim.get("member_welcome") is True:
        if claim.get("declares_once_per_session") is not True:
            return fail(
                "member_welcome_frequency_missing",
                "member welcome must be declared once per session",
            )
        if claim.get("declares_never_interrupt_song") is not True:
            return fail(
                "member_welcome_song_rule_missing",
                "member welcome must be declared never to interrupt a song",
            )
    if claim.get("diamond_to_currency") is not None and (
        not isinstance(claim.get("conversion_source"), str)
        or not claim["conversion_source"].strip()
    ):
        return fail(
            "conversion_source_missing",
            "a diamond-to-currency conversion must declare its source",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "vip_threshold_diamonds": threshold,
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_live_gift_vip(params.get("claim"))
    report_path = out_dir / "live_gift_vip_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_live_gift_vip_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.live_gift_vip_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "claim": {"type": "object"},
                },
                "required": ["claim"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Live gift and VIP gate: gift batch window, trigger "
                "people/diamonds, at most 12 items per batch and 2 "
                "batches per minute, VIP threshold and cooldown, "
                "once-per-session member welcome that never "
                "interrupts a song; conversions need a source."
            ),
        )
    )
    return ["qa.live_gift_vip_gate"]


__all__ = [
    "DEFAULT_VIP_THRESHOLD_DIAMONDS",
    "MAX_BATCHES_PER_MINUTE",
    "MAX_BATCH_ITEMS",
    "check_live_gift_vip",
    "register_live_gift_vip_gate_capabilities_once",
]
