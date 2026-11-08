"""Failed-shot no-hard-cut gate (``qa.failed_shot_no_hard_cut_gate``).

Clean-room restatement of the re-draw discipline described in
the batch-video-plugin review (see
``BATCH_VIDEO_PLUGIN_ATTRIBUTION.md``): a shot whose review
verdict is ``fail`` must never enter the edit timeline -- not
even as a hard cut. It goes onto the re-draw list instead, and
only a fresh take may take its place.

This module judges edit plans only. It never edits media,
never calls a model, and never touches a budget.
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
    issue = {"code": code, "detail": f"qa.failed_shot_no_hard_cut_gate: {detail}"}
    issue.update(extra)
    return issue


def check_edit_plan(plan: Any) -> dict[str, Any]:
    """Judge one edit plan against the failed-shot discipline.

    ``plan`` carries ``shots`` (each with ``id`` and a review
    ``verdict``), ``timeline`` (shot ids in edit order) and
    ``redraw_list`` (shot ids awaiting a fresh take). Verdict
    ``pass`` means no failed shot appears on the timeline and
    every failed shot appears on the redraw list.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("edit plan must be an object")
    shots = plan.get("shots")
    if not isinstance(shots, list) or not shots:
        raise CapabilityError("edit plan requires a non-empty shots list")
    issues: list[dict[str, Any]] = []
    verdict_by_id: dict[str, str] = {}
    for index, shot in enumerate(shots):
        if not isinstance(shot, dict) or not shot.get("id"):
            issues.append(_issue("shot_invalid", f"shot {index} lacks an id"))
            continue
        verdict_by_id[shot["id"]] = shot.get("verdict")
    timeline = plan.get("timeline", [])
    if not isinstance(timeline, list):
        raise CapabilityError("timeline must be a list when present")
    redraw = plan.get("redraw_list", [])
    if not isinstance(redraw, list):
        raise CapabilityError("redraw_list must be a list when present")
    redraw_set = set(redraw)
    for shot_id in timeline:
        if verdict_by_id.get(shot_id) == "fail":
            issues.append(
                _issue(
                    "failed_shot_in_edit",
                    f"failed shot {shot_id} appears on the edit timeline; "
                    "failed shots must go to the redraw list, never to the cut",
                    shot=shot_id,
                )
            )
        elif shot_id not in verdict_by_id:
            issues.append(
                _issue(
                    "timeline_shot_unknown",
                    f"timeline names unknown shot {shot_id}",
                    shot=shot_id,
                )
            )
    for shot_id, verdict in verdict_by_id.items():
        if verdict == "fail" and shot_id not in redraw_set:
            issues.append(
                _issue(
                    "failed_shot_not_requeued",
                    f"failed shot {shot_id} is missing from the redraw list",
                    shot=shot_id,
                )
            )
    verdict = "fail" if issues else "pass"
    return {
        "ok": verdict != "fail",
        "verdict": verdict,
        "issues": issues,
        "not_checked": [],
        "failed_count": sum(1 for v in verdict_by_id.values() if v == "fail"),
        "timeline_count": len(timeline),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_edit_plan(params.get("plan"))
    report_path = out_dir / "failed_shot_no_hard_cut.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_failed_shot_no_hard_cut_gate_capabilities_once() -> list[str]:
    """Register ``qa.failed_shot_no_hard_cut_gate`` (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.failed_shot_no_hard_cut_gate",
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
            description=(
                "Failed-shot gate: a failed shot must never enter the "
                "edit timeline; it goes onto the redraw list instead."
            ),
        )
    )
    return ["qa.failed_shot_no_hard_cut_gate"]


__all__ = [
    "check_edit_plan",
    "register_failed_shot_no_hard_cut_gate_capabilities_once",
]
