"""Dance time-window and rotation-budget gate (``qa.dance_time_window_gate``).

Clean-room restatement of the dance MV methodology (see
``DANCE_MV_METHODOLOGY_ATTRIBUTION.md``): time decides
first, actions second. A window of 0.3–0.6 seconds holds
one short accent; 0.6–1.2 seconds holds one short chain;
1.2–2.5 seconds holds one complete compound phrase; only
past 2.5 seconds may a longer phrase run, and even then
it needs middle goals, not repetition. A hero technique
gets its own window and is never squeezed to make room
for more moves. A whole film normally holds at most two
complete 360-degree turns, each written with its support
foot, axis, drive direction and brake — never just "spin
fast". This gate judges the timing plan only. It dances
nothing, renders nothing, and spends nothing:
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

# Longest window each duration band may carry, in counted
# actions: (upper bound in seconds, max actions).
CAPACITY_BANDS: tuple[tuple[float, int], ...] = (
    (0.6, 1),
    (1.2, 2),
    (2.5, 3),
    (float("inf"), 6),
)
MIN_WINDOW_S = 0.3
MIN_HERO_WINDOW_S = 1.2
MAX_HERO_ACTIONS = 2
MAX_FULL_ROTATIONS = 2


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _max_actions(duration_s: float) -> int:
    for bound, limit in CAPACITY_BANDS:
        if duration_s <= bound:
            return limit
    return CAPACITY_BANDS[-1][1]


def check_dance_time_window(plan: Any) -> dict[str, Any]:
    """Validate a time-window and rotation plan for one dance MV.

    Verdicts are ``pass`` / ``fail`` only. The plan fails
    when a window is shorter than the smallest usable
    window, when a window carries more actions than its
    band allows, when a hero technique is squeezed into
    too short a window, when the film turns fully more
    than twice, or when a turn names no support foot,
    axis or brake.
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
        return fail("plan_not_object", "timing plan must be a JSON object")
    windows = plan.get("windows")
    if not isinstance(windows, list) or not windows:
        return fail("windows_missing", "timing plan must carry at least one window")
    for position, window in enumerate(windows):
        if not isinstance(window, dict):
            return fail(
                "window_not_object",
                f"window {position} must be an object",
            )
        duration = window.get("duration_s")
        if not isinstance(duration, (int, float)) or isinstance(duration, bool):
            return fail(
                "window_duration_missing",
                f"window {position} must state its duration in seconds",
            )
        if duration < MIN_WINDOW_S:
            return fail(
                "window_too_short",
                f"window {position} is {duration}s, below the "
                f"smallest usable window of {MIN_WINDOW_S}s",
            )
        actions = window.get("actions")
        if not isinstance(actions, list) or not actions:
            return fail(
                "window_actions_missing",
                f"window {position} must carry at least one action",
            )
        for action in actions:
            if not isinstance(action, str) or not action.strip():
                return fail(
                    "window_action_missing",
                    f"window {position} carries an unnamed action",
                )
        limit = _max_actions(duration)
        if len(actions) > limit:
            return fail(
                "window_overloaded",
                f"window {position} packs {len(actions)} actions into "
                f"{duration}s; its band allows at most {limit}",
            )
        hero = window.get("hero", False)
        if hero is True:
            if duration < MIN_HERO_WINDOW_S:
                return fail(
                    "hero_window_too_short",
                    f"hero window {position} is {duration}s; a hero "
                    f"technique needs at least {MIN_HERO_WINDOW_S}s",
                )
            if len(actions) > MAX_HERO_ACTIONS:
                return fail(
                    "hero_window_overloaded",
                    f"hero window {position} carries {len(actions)} "
                    f"actions; a hero window holds at most "
                    f"{MAX_HERO_ACTIONS}",
                )
    rotations = plan.get("full_rotations")
    if not isinstance(rotations, int) or isinstance(rotations, bool) or rotations < 0:
        return fail(
            "rotations_missing",
            "timing plan must state its count of complete turns",
        )
    if rotations > MAX_FULL_ROTATIONS:
        return fail(
            "rotations_over_budget",
            f"film turns fully {rotations} times; the budget is {MAX_FULL_ROTATIONS}",
        )
    details = plan.get("rotations")
    if not isinstance(details, list):
        return fail(
            "rotation_details_missing",
            "timing plan must carry a rotation detail list",
        )
    if len(details) != rotations:
        return fail(
            "rotation_count_mismatch",
            f"plan counts {rotations} complete turns but carries {len(details)} rotation details",
        )
    for position, detail in enumerate(details):
        if not isinstance(detail, dict):
            return fail(
                "rotation_not_object",
                f"rotation {position} must be an object",
            )
        for field in ("support_foot", "axis", "brake"):
            if not isinstance(detail.get(field), str) or not detail[field].strip():
                return fail(
                    "rotation_detail_missing",
                    f"rotation {position} must state its {field}",
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
    report = check_dance_time_window(params.get("plan"))
    report_path = out_dir / "dance_time_window_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_dance_time_window_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.dance_time_window_gate",
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
                "Dance time-window and rotation-budget gate: "
                "per-band action capacity, hero techniques in "
                "their own window, and at most two complete turns "
                "with support foot, axis and brake stated."
            ),
        )
    )
    return ["qa.dance_time_window_gate"]


__all__ = [
    "CAPACITY_BANDS",
    "MAX_FULL_ROTATIONS",
    "MAX_HERO_ACTIONS",
    "MIN_HERO_WINDOW_S",
    "MIN_WINDOW_S",
    "check_dance_time_window",
    "register_dance_time_window_gate_capabilities_once",
]
