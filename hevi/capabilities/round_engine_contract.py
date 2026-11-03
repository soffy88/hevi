"""Round-engine state-machine contract (``qa.round_engine_contract``).

Clean-room restatement of the batch-round engine discipline
described in the batch-video-plugin review (see
``BATCH_VIDEO_PLUGIN_ATTRIBUTION.md``): takes move through a
fixed state machine -- queued, dispatched, reported,
reviewed, selected or failed -- and no step may be skipped:
nothing is reported before it is dispatched, nothing is
selected before it is reviewed, and a round closes only when
its caller-declared success cap is reached or its queue is
exhausted.

This module judges event sequences against the contract
only. It dispatches nothing, generates nothing, and never
touches a budget. Every verdict carries
``executed_here: false``: execution stays a separate case.
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

_STATES = ("queued", "dispatched", "reported", "reviewed", "selected", "failed")

_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "queued": ("dispatched",),
    "dispatched": ("reported", "failed"),
    "reported": ("reviewed", "failed"),
    "reviewed": ("selected", "failed", "dispatched"),
    "selected": (),
    "failed": ("queued",),
}

_EVENTS = ("dispatch", "report", "review", "select", "fail", "requeue")


def allowed_transitions(state: str) -> tuple[str, ...]:
    """Return the states reachable from ``state`` under the contract."""
    if state not in _TRANSITIONS:
        raise CapabilityError(f"unknown round-engine state {state!r}")
    return _TRANSITIONS[state]


def check_round_engine_contract(sequence: Any) -> dict[str, Any]:
    """Judge one event sequence against the round-engine contract.

    ``sequence`` carries ``events`` (each with ``take_id`` and
    ``event``), ``max_success_per_round`` (required, positive;
    no default is assumed) and ``round_id``. Verdict ``pass``
    means every event follows a legal transition, no take is
    selected before review, no take is reported before
    dispatch, and the round never records more successes than
    the declared cap.
    """
    if not isinstance(sequence, dict):
        raise CapabilityError("engine sequence must be an object")
    cap = sequence.get("max_success_per_round")
    if not isinstance(cap, int) or isinstance(cap, bool) or cap <= 0:
        raise CapabilityError(
            "engine sequence requires a positive integer "
            "max_success_per_round (no default is assumed)"
        )
    events = sequence.get("events")
    if not isinstance(events, list):
        raise CapabilityError("engine sequence requires an events list")
    issues: list[dict[str, Any]] = []
    states: dict[str, str] = {}
    successes = 0
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            issues.append(_issue("event_not_object", f"event {index} is not an object"))
            continue
        take_id = event.get("take_id")
        name = event.get("event")
        if not take_id:
            issues.append(_issue("event_take_missing", f"event {index} lacks a take_id"))
            continue
        if name not in _EVENTS:
            issues.append(
                _issue("event_unknown", f"event {index} names unknown event {name!r}")
            )
            continue
        current = states.get(take_id, "queued")
        target = {
            "dispatch": "dispatched",
            "report": "reported",
            "review": "reviewed",
            "select": "selected",
            "fail": "failed",
            "requeue": "queued",
        }[name]
        if target not in _TRANSITIONS[current]:
            issues.append(
                _issue(
                    "illegal_transition",
                    f"take {take_id} cannot move {current} -> {target} "
                    f"via {name}",
                    take=take_id,
                )
            )
            continue
        states[take_id] = target
        if name == "select":
            successes += 1
            if successes > cap:
                issues.append(
                    _issue(
                        "round_success_over_cap",
                        f"round records {successes} successes over cap {cap}",
                    )
                )
    verdict = "fail" if issues else "pass"
    return {
        "ok": verdict != "fail",
        "verdict": verdict,
        "issues": issues,
        "not_checked": [],
        "take_states": states,
        "success_count": successes,
        "executed_here": False,
    }


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.round_engine_contract: {detail}"}
    issue.update(extra)
    return issue


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_round_engine_contract(params.get("sequence"))
    report_path = out_dir / "round_engine_contract.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_round_engine_contract_capabilities_once() -> list[str]:
    """Register ``qa.round_engine_contract`` (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.round_engine_contract",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "sequence": {"type": "object"},
                },
                "required": ["sequence"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Round-engine state-machine contract: queued, "
                "dispatched, reported, reviewed, selected or failed; "
                "no step skippable, successes capped by caller "
                "declaration. Contract only; nothing executes here."
            ),
        )
    )
    return ["qa.round_engine_contract"]


__all__ = [
    "allowed_transitions",
    "check_round_engine_contract",
    "register_round_engine_contract_capabilities_once",
]
