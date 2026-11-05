"""Live gift batch schema (``video.live_gift_batch_schema``).

Fake-level contract for a live gift batching and VIP plan of
the kind described in the cyber-xiaoya-live review (see
``CYBER_XIAOYA_ATTRIBUTION.md``): gifts batched inside a
window with a people/diamond trigger, at most 12 items per
batch and at most 2 batches per minute, a VIP threshold with
cooldown and face display, a once-per-session member welcome
that never interrupts a song, and a statistics panel. The
contract certifies the shape of the plan only. It touches no
payment and no platform: every compiled contract declares
``executed_here: false``. Whether gifts actually arrive is a
question for a real platform session, which is a separate
platform-account case.
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

MAX_BATCH_ITEMS = 12
MAX_BATCHES_PER_MINUTE = 2
STAT_PANELS: frozenset[str] = frozenset(
    {"token_usage", "vidu_credits", "gift_diamonds", "memory_rounds"}
)


def compile_live_gift_batch(plan: Any) -> dict[str, Any]:
    """Compile one live gift batch and VIP contract.

    ``plan`` carries ``batch`` (window, trigger people and
    diamonds, at most 12 items, at most 2 per minute), ``vip``
    (threshold, cooldown, face display), ``member_welcome``
    (enabled, once per session, never interrupt song) and
    ``stats`` (panels from the closed panel vocabulary). A
    diamond-to-currency conversion needs a declared source.
    Raises :class:`CapabilityError` on any shape violation or
    on any claim that gift handling ran here. The returned
    contract records that nothing was executed here.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("live gift batch plan must be an object")
    if plan.get("executed_here") is True or plan.get("gifts_received") is True:
        raise CapabilityError("gift claims are refused here; this contract receives nothing")
    batch = plan.get("batch")
    if not isinstance(batch, dict):
        raise CapabilityError("live gift batch plan requires a batch object")
    window = batch.get("window_seconds")
    if not isinstance(window, int) or isinstance(window, bool) or window < 1 or window > 60:
        raise CapabilityError("batch window_seconds must be an integer within 1..60")
    trigger_people = batch.get("trigger_people")
    if (
        not isinstance(trigger_people, int)
        or isinstance(trigger_people, bool)
        or trigger_people < 1
    ):
        raise CapabilityError("batch trigger_people must be an integer >= 1")
    trigger_diamonds = batch.get("trigger_diamonds")
    if (
        not isinstance(trigger_diamonds, int)
        or isinstance(trigger_diamonds, bool)
        or trigger_diamonds < 0
    ):
        raise CapabilityError("batch trigger_diamonds must be an integer >= 0")
    max_items = batch.get("max_items")
    if (
        not isinstance(max_items, int)
        or isinstance(max_items, bool)
        or max_items < 1
        or max_items > MAX_BATCH_ITEMS
    ):
        raise CapabilityError("batch max_items must be an integer within 1..12")
    max_per_minute = batch.get("max_per_minute")
    if (
        not isinstance(max_per_minute, int)
        or isinstance(max_per_minute, bool)
        or max_per_minute < 1
        or max_per_minute > MAX_BATCHES_PER_MINUTE
    ):
        raise CapabilityError("batch max_per_minute must be an integer within 1..2")
    vip = plan.get("vip")
    if not isinstance(vip, dict):
        raise CapabilityError("live gift batch plan requires a vip object")
    threshold = vip.get("threshold_diamonds")
    if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold < 1:
        raise CapabilityError("vip threshold_diamonds must be an integer >= 1")
    cooldown = vip.get("cooldown_seconds")
    if not isinstance(cooldown, int) or isinstance(cooldown, bool) or cooldown < 0:
        raise CapabilityError("vip cooldown_seconds must be an integer >= 0")
    if not isinstance(vip.get("face_display"), bool):
        raise CapabilityError("vip face_display must be a boolean")
    welcome = plan.get("member_welcome")
    if not isinstance(welcome, dict):
        raise CapabilityError("live gift batch plan requires a member_welcome object")
    if not isinstance(welcome.get("enabled"), bool):
        raise CapabilityError("member_welcome enabled must be a boolean")
    if welcome.get("enabled") is True:
        if welcome.get("once_per_session") is not True:
            raise CapabilityError("member welcome must be once per session")
        if welcome.get("never_interrupt_song") is not True:
            raise CapabilityError("member welcome must never interrupt a song")
    stats = plan.get("stats")
    if not isinstance(stats, dict):
        raise CapabilityError("live gift batch plan requires a stats object")
    panels = stats.get("panels")
    if not isinstance(panels, list) or not panels:
        raise CapabilityError("stats needs a non-empty panels list")
    unknown = [panel for panel in panels if panel not in STAT_PANELS]
    if unknown:
        raise CapabilityError(f"unknown stats panel: {unknown[0]}")
    if plan.get("diamond_to_currency") is not None and (
        not isinstance(plan.get("conversion_source"), str) or not plan["conversion_source"].strip()
    ):
        raise CapabilityError("a diamond-to-currency conversion must declare its source")
    return {
        "contract": "live-gift-batch",
        "batch_window_seconds": window,
        "vip_threshold_diamonds": threshold,
        "vip_cooldown_seconds": cooldown,
        "member_welcome_enabled": welcome["enabled"],
        "stat_panels": list(panels),
        "executed_here": False,
        "gifts_received": False,
        "payment_case": "separate_platform_account_case",
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = compile_live_gift_batch(params.get("plan"))
    report_path = out_dir / "live_gift_batch_contract.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "vip_threshold_diamonds": report["vip_threshold_diamonds"],
            "executed_here": False,
        },
    )


def register_live_gift_batch_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.live_gift_batch_schema",
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
                "Live gift batch schema (fake): batch window and "
                "trigger, at most 12 items per batch and 2 batches "
                "per minute, VIP threshold, cooldown and face "
                "display, once-per-session member welcome, stats "
                "panels; no payment or platform is touched here."
            ),
        )
    )
    return ["video.live_gift_batch_schema"]


__all__ = [
    "MAX_BATCHES_PER_MINUTE",
    "MAX_BATCH_ITEMS",
    "STAT_PANELS",
    "compile_live_gift_batch",
    "register_live_gift_batch_schema_capabilities_once",
]
