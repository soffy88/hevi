"""Xiaoya danmaku queue and gift gate (``qa.xiaoya_danmaku_queue_gift_gate``).

The branch under review queues incoming danmaku commands
under one of three closed policies: plain first-in-first-out
(the default, steadiest rhythm), gifts first then FIFO, or
gifts first with a random pick inside the recent window. Under
the default policy a gift never jumps the queue. Commands
expire after a maximum age (measured 180 seconds) and the
queue caps at a maximum size (measured 200); when the queue is
full, non-gift commands are dropped before gifts.

Clean-room restatement of the method found in the
``live-parity`` branch checkout (see
``DIGITAL_HOST_IMPROVEMENT_ATTRIBUTION.md``). This gate judges
the shape of a queue declaration only; it never reads a live
danmaku feed and never touches any gift or payment.
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

# The three queue policies, as measured in the branch.
POLICIES: frozenset[str] = frozenset({"fifo", "gift_first_fifo", "gift_first_random"})

# Measured defaults from the branch.
MEASURED_MAX_AGE_SECONDS = 180
MEASURED_MAX_SIZE = 200


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def check_xiaoya_danmaku_queue_gift(plan: Any) -> dict[str, Any]:
    """Validate a danmaku queue-and-gift declaration.

    Verdicts are ``pass`` / ``fail`` only. The plan fails when
    it is not an object, when its policy is outside the closed
    three-policy set, when a gift jumps the queue under the
    default FIFO policy, when no maximum age or maximum size
    is declared, when a full queue does not drop non-gift
    commands first, or when expiry is not enabled.
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
    policy = plan.get("policy")
    if policy not in POLICIES:
        return fail(
            "unknown_policy",
            "policy must be one of fifo, gift_first_fifo, gift_first_random",
        )
    if policy == "fifo" and plan.get("gift_jumps_queue") is True:
        return fail(
            "gift_queue_jump",
            "under the default fifo policy a gift never jumps the queue",
        )
    max_age = plan.get("max_age_seconds")
    if not _is_int(max_age) or max_age <= 0:
        return fail(
            "max_age_missing",
            "a maximum command age in seconds must be declared (measured 180)",
        )
    max_size = plan.get("max_size")
    if not _is_int(max_size) or max_size <= 0:
        return fail(
            "max_size_missing",
            "a maximum queue size must be declared (measured 200)",
        )
    if plan.get("full_queue_drops_non_gift_first") is not True:
        return fail(
            "full_queue_drop_missing",
            "a full queue must drop non-gift commands before gifts",
        )
    if plan.get("expiry_enabled") is not True:
        return fail(
            "expiry_missing",
            "expiry of stale commands must be enabled",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
        "policy": policy,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_xiaoya_danmaku_queue_gift(params.get("plan"))
    report_path = out_dir / "xiaoya_danmaku_queue_gift_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_xiaoya_danmaku_queue_gift_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.xiaoya_danmaku_queue_gift_gate",
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
                "xiaoya danmaku queue and gift gate: closed three "
                "policies, gifts never jump the default queue, "
                "maximum age and size, full queue drops non-gifts "
                "first, expiry enabled."
            ),
        )
    )
    return ["qa.xiaoya_danmaku_queue_gift_gate"]


__all__ = [
    "MEASURED_MAX_AGE_SECONDS",
    "MEASURED_MAX_SIZE",
    "POLICIES",
    "check_xiaoya_danmaku_queue_gift",
    "register_xiaoya_danmaku_queue_gift_gate_capabilities_once",
]
