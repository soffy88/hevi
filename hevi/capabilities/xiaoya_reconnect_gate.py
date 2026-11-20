"""Xiaoya reconnect gate (``qa.xiaoya_reconnect_gate``).

When the encoder or the push sink drops, the stream reopens
automatically: the branch under review waits a 3-second
cooldown, then restarts, at most 6 successful restarts inside
a 3600-second sliding window, and goes silent after the cap
instead of retrying forever. On reopening the host speaks a
resume line and keeps its memory: the topic pool, the queue,
and the conversation do not reset.

Clean-room restatement of the method found in the
``live-parity`` branch checkout (see
``DIGITAL_HOST_IMPROVEMENT_ATTRIBUTION.md``). This gate judges
the shape of a reconnect declaration only; it never opens a
connection and never starts a stream.
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

# Measured reconnect numbers from the branch.
MIN_DELAY_SECONDS = 3.0
MAX_HOURLY_RESTARTS = 6
MIN_WINDOW_SECONDS = 3600.0


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def check_xiaoya_reconnect(plan: Any) -> dict[str, Any]:
    """Validate a reconnect declaration.

    Verdicts are ``pass`` / ``fail`` only. The plan fails when
    it is not an object, when the cooldown is shorter than the
    measured 3 seconds, when the hourly restart cap is missing
    or above the measured 6, when the sliding window is shorter
    than the measured 3600 seconds, when no resume line is
    declared, when memory is not kept across the reconnect, or
    when the plan does not go silent after the cap.
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
    delay = plan.get("delay_seconds")
    if not _is_number(delay) or delay < MIN_DELAY_SECONDS:
        return fail(
            "cooldown_too_short",
            "the reconnect cooldown must be at least the measured 3 seconds",
        )
    hourly_cap = plan.get("hourly_cap")
    if not _is_int(hourly_cap) or hourly_cap <= 0 or hourly_cap > MAX_HOURLY_RESTARTS:
        return fail(
            "hourly_cap_wrong",
            "the hourly restart cap must be a positive integer no larger than the measured 6",
        )
    window = plan.get("window_seconds")
    if not _is_number(window) or window < MIN_WINDOW_SECONDS:
        return fail(
            "window_too_short",
            "the sliding window must be at least the measured 3600 seconds",
        )
    if plan.get("resume_speech_present") is not True:
        return fail(
            "resume_speech_missing",
            "a resume line for the reopened stream must be declared",
        )
    if plan.get("memory_kept") is not True:
        return fail(
            "memory_lost",
            "memory must be kept across a reconnect: no reset of topics, queue, or conversation",
        )
    if plan.get("silent_after_cap") is not True:
        return fail(
            "silent_after_cap_missing",
            "the plan must go silent after the hourly cap instead of retrying forever",
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
    report = check_xiaoya_reconnect(params.get("plan"))
    report_path = out_dir / "xiaoya_reconnect_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_xiaoya_reconnect_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.xiaoya_reconnect_gate",
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
                "xiaoya reconnect gate: 3-second cooldown, at most "
                "6 restarts per 3600-second window, resume line, "
                "memory kept, silent after the cap."
            ),
        )
    )
    return ["qa.xiaoya_reconnect_gate"]


__all__ = [
    "MAX_HOURLY_RESTARTS",
    "MIN_DELAY_SECONDS",
    "MIN_WINDOW_SECONDS",
    "check_xiaoya_reconnect",
    "register_xiaoya_reconnect_gate_capabilities_once",
]
