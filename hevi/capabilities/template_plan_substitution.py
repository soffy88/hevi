"""Template-planner substitution contract (``qa.template_plan_substitution``).

Clean-room restatement of the planning substitution point
described in the batch-video-plugin review (see
``BATCH_VIDEO_PLUGIN_ATTRIBUTION.md``): shot planning has a
single replaceable entry point. The built-in planner lays out
beats across a four-part arc -- opening, development, turn,
close -- and a caller-supplied planner may replace it only
through the same declared signature, returning beats that
tile the declared total duration in arc order.

This module judges contracts and beat lists only. It plans
nothing itself, calls no model, and never touches a budget.
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

_ARC = ("opening", "development", "turn", "close")
_REQUIRED_PARAMETERS = ("story_text", "shot_count")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.template_plan_substitution: {detail}"}
    issue.update(extra)
    return issue


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_template_planner_contract(contract: Any) -> dict[str, Any]:
    """Judge one planner substitution contract and its beats.

    ``contract`` carries ``planner`` (with ``entry_point`` and
    ``parameters``), ``returns`` (naming the beat list), and
    ``beats`` (each with ``start_s``, ``end_s`` and an ``arc``
    position), plus ``total_duration_s``. Verdict ``pass``
    means the entry point declares exactly the required
    parameters, returns beats, and the beats tile the total
    duration in arc order without gaps or overlap.
    """
    if not isinstance(contract, dict):
        raise CapabilityError("planner contract must be an object")
    issues: list[dict[str, Any]] = []
    planner = contract.get("planner")
    if not isinstance(planner, dict) or not planner.get("entry_point"):
        issues.append(
            _issue("planner_entry_missing", "planner entry_point is required")
        )
    else:
        parameters = planner.get("parameters")
        if list(parameters or []) != list(_REQUIRED_PARAMETERS):
            issues.append(
                _issue(
                    "planner_signature_mismatch",
                    "planner parameters must be exactly "
                    f"{list(_REQUIRED_PARAMETERS)}",
                )
            )
    returns = contract.get("returns", [])
    if "beats" not in returns:
        issues.append(
            _issue("planner_return_missing", "planner must return a beats list")
        )
    beats = contract.get("beats")
    if not isinstance(beats, list) or not beats:
        raise CapabilityError("planner contract requires a non-empty beats list")
    cursor = 0.0
    arc_seen: list[str] = []
    for index, beat in enumerate(beats):
        if not isinstance(beat, dict):
            issues.append(_issue("beat_not_object", f"beat {index} is not an object"))
            continue
        start, end = beat.get("start_s"), beat.get("end_s")
        if not _is_number(start) or not _is_number(end) or end <= start:
            issues.append(
                _issue("beat_window_invalid", f"beat {index} has an invalid window")
            )
            continue
        if abs(start - cursor) > 1e-6:
            issues.append(
                _issue(
                    "beat_tiling_gap_or_overlap",
                    f"beat {index} starts at {start}s, expected {cursor}s",
                )
            )
        cursor = end
        arc = beat.get("arc")
        if arc not in _ARC:
            issues.append(
                _issue("beat_arc_unknown", f"beat {index} arc must be one of {_ARC}")
            )
        else:
            arc_seen.append(arc)
    if arc_seen:
        order = [_ARC.index(a) for a in arc_seen]
        if order != sorted(order):
            issues.append(
                _issue(
                    "arc_order_broken",
                    "beats must follow the arc order opening, development, "
                    "turn, close",
                )
            )
        if arc_seen[0] != "opening" or arc_seen[-1] != "close":
            issues.append(
                _issue(
                    "arc_endpoints_missing",
                    "beats must start at opening and end at close",
                )
            )
    total = contract.get("total_duration_s")
    if _is_number(total) and abs(total - cursor) > 1e-6:
        issues.append(
            _issue(
                "total_duration_mismatch",
                f"declared total {total}s does not match tiled {cursor}s",
            )
        )
    verdict = "fail" if issues else "pass"
    return {
        "ok": verdict != "fail",
        "verdict": verdict,
        "issues": issues,
        "not_checked": [],
        "beat_count": len(beats),
        "tiled_duration_s": cursor,
        "executed_here": False,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_template_planner_contract(params.get("contract"))
    report_path = out_dir / "template_plan_substitution.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_template_plan_substitution_capabilities_once() -> list[str]:
    """Register ``qa.template_plan_substitution`` (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.template_plan_substitution",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "contract": {"type": "object"},
                },
                "required": ["contract"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Template-planner substitution contract: a replacement "
                "planner uses the same declared signature and returns "
                "beats tiling the total in arc order. Contract only."
            ),
        )
    )
    return ["qa.template_plan_substitution"]


__all__ = [
    "check_template_planner_contract",
    "register_template_plan_substitution_capabilities_once",
]
