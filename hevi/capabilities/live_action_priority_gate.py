"""Live action priority gate (``qa.live_action_priority_gate``).

Clean-room restatement of the cyber-xiaoya-live review (see
``CYBER_XIAOYA_ATTRIBUTION.md``): the upstream live system
orders actions in four priority levels, VIP above manual above
fixed choreography above danmaku, with first-in-first-out
order inside one level, and choreography spacing declared per
group and between groups. This gate judges claims about such
an ordering only: the four levels must be complete and in
exactly that order, same-level FIFO must be declared, and the
choreography group and gap intervals must be declared. A
missing level or a reversed order fails. This gate executes
nothing: ``executed_here`` is always false.
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

PRIORITY_ORDER: tuple[str, ...] = ("vip", "manual", "choreo", "danmaku")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_live_action_priority(claim: Any) -> dict[str, Any]:
    """Validate a claim about live action priority ordering.

    Verdicts are ``pass`` / ``fail`` only. The priority order
    must be exactly VIP, manual, choreography, danmaku;
    same-level FIFO must be declared; the choreography group
    interval and gap interval must be declared.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "priority_order": None,
            "executed_here": False,
        }

    if not isinstance(claim, dict):
        return fail(
            "claim_not_object",
            "live action priority claim must be a JSON object",
        )
    order = claim.get("priority_order")
    if not isinstance(order, list) or [str(level) for level in order] != list(PRIORITY_ORDER):
        return fail(
            "priority_order_wrong",
            "priority order must be exactly vip, manual, choreo, danmaku",
        )
    if claim.get("same_level_fifo") is not True:
        return fail(
            "fifo_not_declared",
            "same-level first-in-first-out order must be declared",
        )
    group_interval = claim.get("choreo_group_interval_seconds")
    if (
        not isinstance(group_interval, (int, float))
        or isinstance(group_interval, bool)
        or group_interval <= 0
    ):
        return fail(
            "choreo_group_interval_missing",
            "choreography needs a declared in-group interval in seconds",
        )
    gap = claim.get("choreo_gap_seconds")
    if not isinstance(gap, (int, float)) or isinstance(gap, bool) or gap <= 0:
        return fail(
            "choreo_gap_missing",
            "choreography needs a declared between-group gap in seconds",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "priority_order": list(PRIORITY_ORDER),
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_live_action_priority(params.get("claim"))
    report_path = out_dir / "live_action_priority_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_live_action_priority_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.live_action_priority_gate",
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
                "Live action priority gate: four levels in exactly "
                "VIP, manual, choreography, danmaku order, same-level "
                "FIFO, and declared choreography group and gap "
                "intervals."
            ),
        )
    )
    return ["qa.live_action_priority_gate"]


__all__ = [
    "PRIORITY_ORDER",
    "check_live_action_priority",
    "register_live_action_priority_gate_capabilities_once",
]
