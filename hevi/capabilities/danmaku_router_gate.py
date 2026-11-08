"""Danmaku router gate (``qa.danmaku_router_gate``).

Clean-room restatement of the cyber-xiaoya-live review (see
``CYBER_XIAOYA_ATTRIBUTION.md``): the upstream live system routes
incoming chat through a router with a priority queue, batching
(at most 14 per batch, one read per batch), command recognition
with explicit confirm/dismiss, a drop-word list, a speaker-side
banned-word list, a reply interval and at most 2 replies per
round. Chat arrives from a collector: the public web socket
needs no login, while a third-party collector may need a
platform account or cookie and carries compliance risk the
collector user bears alone. This gate judges claims about such
a router only: any missing piece fails, a third-party collector
without a risk declaration fails, and a no-login claim on a
cookie route fails. This gate executes nothing and connects to
no collector: ``executed_here`` is always false, and real
collection is a separate platform-account case.
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

MAX_BATCH = 14
MAX_REPLIES_PER_ROUND = 2
COLLECTOR_SOURCES: frozenset[str] = frozenset(
    {"official_open", "public_web_websocket", "third_party_collector", "none"}
)


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_danmaku_router(claim: Any) -> dict[str, Any]:
    """Validate a claim about a danmaku router.

    Verdicts are ``pass`` / ``fail`` only. The router must have
    a priority queue, a batch limit within 1..14, command
    confirm and dismiss, a non-empty drop-word list and a
    non-empty speaker-side banned-word list, a reply interval
    and at most 2 replies per round; a third-party collector
    must declare its compliance risk, and a cookie route must
    not be claimed login-free.
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
            "danmaku router claim must be a JSON object",
        )
    if claim.get("has_priority_queue") is not True:
        return fail(
            "priority_queue_missing",
            "danmaku router needs a priority queue",
        )
    batch_limit = claim.get("batch_limit")
    if not isinstance(batch_limit, int) or isinstance(batch_limit, bool):
        return fail(
            "batch_limit_missing",
            "danmaku router needs a batch limit",
        )
    if batch_limit < 1 or batch_limit > MAX_BATCH:
        return fail(
            "batch_limit_out_of_range",
            "batch limit must be within 1..14",
        )
    if claim.get("has_command_confirm") is not True:
        return fail(
            "command_confirm_missing",
            "danmaku router needs command confirm handling",
        )
    if claim.get("has_command_dismiss") is not True:
        return fail(
            "command_dismiss_missing",
            "danmaku router needs command dismiss handling",
        )
    drop_words = claim.get("drop_words")
    if not isinstance(drop_words, list) or not drop_words:
        return fail(
            "drop_words_missing",
            "danmaku router needs a non-empty drop-word list",
        )
    banned = claim.get("speaker_side_banned_words")
    if not isinstance(banned, list) or not banned:
        return fail(
            "speaker_banned_words_missing",
            "danmaku router needs a non-empty speaker-side banned-word list",
        )
    interval = claim.get("reply_interval_ms")
    if not isinstance(interval, int) or isinstance(interval, bool) or interval < 0:
        return fail(
            "reply_interval_missing",
            "danmaku router needs a reply interval in milliseconds",
        )
    max_replies = claim.get("max_replies_per_round")
    if not isinstance(max_replies, int) or isinstance(max_replies, bool):
        return fail(
            "max_replies_missing",
            "danmaku router needs a max-replies-per-round figure",
        )
    if max_replies < 1 or max_replies > MAX_REPLIES_PER_ROUND:
        return fail(
            "max_replies_out_of_range",
            "at most 2 replies per round",
        )
    collector = claim.get("collector_source")
    if collector not in COLLECTOR_SOURCES:
        return fail(
            "collector_source_unknown",
            "collector source must be one of official_open, "
            "public_web_websocket, third_party_collector, none",
        )
    if collector == "third_party_collector":
        if claim.get("declares_collector_risk") is not True:
            return fail(
                "collector_risk_not_declared",
                "a third-party collector carries compliance risk the "
                "collector user bears alone; it must be declared",
            )
        if claim.get("declares_no_login_needed") is True:
            return fail(
                "cookie_route_claimed_login_free",
                "a third-party collector route that needs a platform "
                "account or cookie cannot be claimed login-free",
            )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "batch_limit": batch_limit,
        "collector_source": collector,
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_danmaku_router(params.get("claim"))
    report_path = out_dir / "danmaku_router_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_danmaku_router_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.danmaku_router_gate",
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
                "Danmaku router gate: priority queue, batch limit "
                "1..14, command confirm/dismiss, drop words and "
                "speaker-side banned words, reply interval and at "
                "most 2 replies per round; third-party collectors "
                "must declare their compliance risk."
            ),
        )
    )
    return ["qa.danmaku_router_gate"]


__all__ = [
    "COLLECTOR_SOURCES",
    "MAX_BATCH",
    "MAX_REPLIES_PER_ROUND",
    "check_danmaku_router",
    "register_danmaku_router_gate_capabilities_once",
]
