"""Stale-round watchdog gate (``qa.stale_round_watchdog_gate``).

Clean-room restatement of the idle-round takeover discipline
described in the batch-video-plugin review (see
``BATCH_VIDEO_PLUGIN_ATTRIBUTION.md``): a round that has gone
quiet for longer than a caller-declared stall threshold must be
taken over by a watchdog, and every takeover must be recorded
in the ledger. A takeover claimed for a round that was not
actually idle, or recorded before the round went quiet, is a
forged record and fails.

This module judges records only. It never watches a live
queue, never dispatches work, and never touches a budget.
The stall threshold and the watchdog patrol interval have no
defaults: the caller must declare both.
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


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.stale_round_watchdog_gate: {detail}"}
    issue.update(extra)
    return issue


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_stale_round_watchdog(record: Any) -> dict[str, Any]:
    """Judge one watchdog record against the stale-round discipline.

    ``record`` carries ``rounds`` (each with ``id`` and
    ``last_activity_at``, an epoch timestamp), ``stall_threshold_s``
    and ``watchdog_interval_s`` (both required, positive), and
    ``takeovers`` (each with ``round_id``, ``taken_at`` and a
    ``ledger_note``). Verdict ``pass`` means every round idle
    beyond the threshold has a recorded takeover, every takeover
    is ledger-noted, and no takeover predates the idleness it
    claims to answer.
    """
    if not isinstance(record, dict):
        raise CapabilityError("watchdog record must be an object")
    threshold = record.get("stall_threshold_s")
    if not _is_number(threshold) or threshold <= 0:
        raise CapabilityError(
            "watchdog record requires a positive stall_threshold_s "
            "(no default is assumed)"
        )
    interval = record.get("watchdog_interval_s")
    if not _is_number(interval) or interval <= 0:
        raise CapabilityError(
            "watchdog record requires a positive watchdog_interval_s "
            "(no default is assumed)"
        )
    now = record.get("checked_at")
    if not _is_number(now):
        raise CapabilityError("watchdog record requires a numeric checked_at epoch")
    rounds = record.get("rounds")
    if not isinstance(rounds, list) or not rounds:
        raise CapabilityError("watchdog record requires a non-empty rounds list")
    issues: list[dict[str, Any]] = []
    round_by_id: dict[str, dict[str, Any]] = {}
    for index, round_ in enumerate(rounds):
        if not isinstance(round_, dict) or not round_.get("id"):
            issues.append(_issue("round_invalid", f"round {index} lacks an id"))
            continue
        if not _is_number(round_.get("last_activity_at")):
            issues.append(
                _issue(
                    "last_activity_missing",
                    f"round {round_['id']} lacks a numeric last_activity_at",
                    round=round_["id"],
                )
            )
            continue
        round_by_id[round_["id"]] = round_
    takeovers = record.get("takeovers", [])
    if not isinstance(takeovers, list):
        raise CapabilityError("takeovers must be a list when present")
    taken_ids: set[str] = set()
    for takeover in takeovers:
        if not isinstance(takeover, dict) or not takeover.get("round_id"):
            issues.append(_issue("takeover_invalid", "takeover entry lacks a round_id"))
            continue
        round_id = takeover["round_id"]
        taken_ids.add(round_id)
        if not takeover.get("ledger_note"):
            issues.append(
                _issue(
                    "takeover_unrecorded",
                    f"takeover for round {round_id} lacks a ledger note",
                    round=round_id,
                )
            )
        taken_at = takeover.get("taken_at")
        if not _is_number(taken_at):
            issues.append(
                _issue(
                    "takeover_time_missing",
                    f"takeover for round {round_id} lacks a numeric taken_at",
                    round=round_id,
                )
            )
            continue
        round_ = round_by_id.get(round_id)
        if round_ is None:
            issues.append(
                _issue(
                    "takeover_unknown_round",
                    f"takeover names unknown round {round_id}",
                    round=round_id,
                )
            )
            continue
        idle_at_takeover = taken_at - round_["last_activity_at"]
        if idle_at_takeover < 0:
            issues.append(
                _issue(
                    "takeover_predates_activity",
                    f"takeover for round {round_id} predates its last activity",
                    round=round_id,
                )
            )
        elif idle_at_takeover < threshold:
            issues.append(
                _issue(
                    "takeover_without_stall",
                    f"takeover for round {round_id} claims a stall after "
                    f"only {idle_at_takeover}s idle (threshold {threshold}s)",
                    round=round_id,
                )
            )
    for round_id, round_ in round_by_id.items():
        idle = now - round_["last_activity_at"]
        if idle > threshold and round_id not in taken_ids:
            issues.append(
                _issue(
                    "stale_round_untaken",
                    f"round {round_id} idle {idle}s over threshold {threshold}s "
                    "with no recorded takeover",
                    round=round_id,
                )
            )
    verdict = "fail" if issues else "pass"
    return {
        "ok": verdict != "fail",
        "verdict": verdict,
        "issues": issues,
        "not_checked": [],
        "round_count": len(round_by_id),
        "stale_count": sum(
            1
            for r in round_by_id.values()
            if now - r["last_activity_at"] > threshold
        ),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_stale_round_watchdog(params.get("record"))
    report_path = out_dir / "stale_round_watchdog.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_stale_round_watchdog_gate_capabilities_once() -> list[str]:
    """Register ``qa.stale_round_watchdog_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.stale_round_watchdog_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "record": {"type": "object"},
                },
                "required": ["record"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Stale-round watchdog gate: rounds idle beyond a "
                "caller-declared threshold must have a ledger-recorded "
                "takeover, and no takeover may predate the idleness it "
                "claims to answer."
            ),
        )
    )
    return ["qa.stale_round_watchdog_gate"]


__all__ = [
    "check_stale_round_watchdog",
    "register_stale_round_watchdog_gate_capabilities_once",
]
