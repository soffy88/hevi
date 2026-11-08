"""Danmaku route schema (``video.danmaku_route_schema``).

Fake-level contract for a danmaku routing plan of the kind
described in the cyber-xiaoya-live review (see
``CYBER_XIAOYA_ATTRIBUTION.md``): a priority queue, batching
(at most 14 per batch), command confirm and dismiss, a
drop-word list, a speaker-side banned-word list, a collector
declaration and a reply interval with at most 2 replies per
round. The contract certifies the shape of the plan only. It
connects to no collector and reads no live chat: every compiled
contract declares ``executed_here: false``. Whether chat
actually flows is a question for a real collector, which is a
separate platform-account case.
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

MAX_BATCH = 14
MAX_REPLIES_PER_ROUND = 2
COLLECTOR_SOURCES: frozenset[str] = frozenset(
    {"official_open", "public_web_websocket", "third_party_collector", "none"}
)


def compile_danmaku_route(plan: Any) -> dict[str, Any]:
    """Compile one danmaku routing contract.

    ``plan`` carries ``batch`` (``max`` 1..14 and
    ``read_per_batch``), ``priority_queue`` true, ``commands``
    (confirm and dismiss true), ``filters`` (non-empty
    ``drop_words`` and ``speaker_side_banned_words``),
    ``collector`` (a declared source; a third-party source must
    declare its risk) and ``reply`` (``interval_ms`` and at most
    2 ``max_replies_per_round``). Raises
    :class:`CapabilityError` on any shape violation or on any
    claim that routing ran here. The returned contract records
    that nothing was executed here.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("danmaku route plan must be an object")
    if plan.get("executed_here") is True or plan.get("routing_ran") is True:
        raise CapabilityError("routing claims are refused here; this contract routes nothing")
    batch = plan.get("batch")
    if not isinstance(batch, dict):
        raise CapabilityError("danmaku route plan requires a batch object")
    batch_max = batch.get("max")
    if (
        not isinstance(batch_max, int)
        or isinstance(batch_max, bool)
        or batch_max < 1
        or batch_max > MAX_BATCH
    ):
        raise CapabilityError("batch max must be an integer within 1..14")
    read_per_batch = batch.get("read_per_batch")
    if (
        not isinstance(read_per_batch, int)
        or isinstance(read_per_batch, bool)
        or read_per_batch < 1
    ):
        raise CapabilityError("batch read_per_batch must be an integer >= 1")
    if plan.get("priority_queue") is not True:
        raise CapabilityError("danmaku route plan requires a priority queue")
    commands = plan.get("commands")
    if not isinstance(commands, dict):
        raise CapabilityError("danmaku route plan requires a commands object")
    if commands.get("confirm") is not True:
        raise CapabilityError("danmaku route plan requires command confirm")
    if commands.get("dismiss") is not True:
        raise CapabilityError("danmaku route plan requires command dismiss")
    filters = plan.get("filters")
    if not isinstance(filters, dict):
        raise CapabilityError("danmaku route plan requires a filters object")
    drop_words = filters.get("drop_words")
    if not isinstance(drop_words, list) or not drop_words:
        raise CapabilityError("danmaku route plan needs a non-empty drop-word list")
    banned = filters.get("speaker_side_banned_words")
    if not isinstance(banned, list) or not banned:
        raise CapabilityError("danmaku route plan needs a non-empty speaker-side banned-word list")
    collector = plan.get("collector")
    if not isinstance(collector, dict):
        raise CapabilityError("danmaku route plan requires a collector object")
    if collector.get("source") not in COLLECTOR_SOURCES:
        raise CapabilityError(
            "collector source must be one of official_open, "
            "public_web_websocket, third_party_collector, none"
        )
    if (
        collector.get("source") == "third_party_collector"
        and collector.get("declares_risk") is not True
    ):
        raise CapabilityError("a third-party collector must declare its compliance risk")
    reply = plan.get("reply")
    if not isinstance(reply, dict):
        raise CapabilityError("danmaku route plan requires a reply object")
    interval = reply.get("interval_ms")
    if not isinstance(interval, int) or isinstance(interval, bool) or interval < 0:
        raise CapabilityError("reply interval_ms must be an integer >= 0")
    max_replies = reply.get("max_replies_per_round")
    if (
        not isinstance(max_replies, int)
        or isinstance(max_replies, bool)
        or max_replies < 1
        or max_replies > MAX_REPLIES_PER_ROUND
    ):
        raise CapabilityError("at most 2 replies per round")
    return {
        "contract": "danmaku-route",
        "batch_max": batch_max,
        "read_per_batch": read_per_batch,
        "collector_source": collector["source"],
        "reply_interval_ms": interval,
        "max_replies_per_round": max_replies,
        "executed_here": False,
        "routing_ran": False,
        "collector_case": "separate_platform_account_case",
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = compile_danmaku_route(params.get("plan"))
    report_path = out_dir / "danmaku_route_contract.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "batch_max": report["batch_max"],
            "executed_here": False,
        },
    )


def register_danmaku_route_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.danmaku_route_schema",
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
                "Danmaku route schema (fake): priority queue, batch "
                "max 1..14, command confirm/dismiss, drop words and "
                "speaker-side banned words, declared collector, reply "
                "interval and at most 2 replies per round; no "
                "collector is connected here."
            ),
        )
    )
    return ["video.danmaku_route_schema"]


__all__ = [
    "COLLECTOR_SOURCES",
    "MAX_BATCH",
    "MAX_REPLIES_PER_ROUND",
    "compile_danmaku_route",
    "register_danmaku_route_schema_capabilities_once",
]
