"""Talkback edit gate (``qa.talkback_edit_gate``).

A recorded talkback is edited in four moves: cut the dead
silence, align the subtitles, insert cutaway stills where the
talk names a concrete step, and keep the result watchable
without sound. The expensive failure this gate exists to stop
is the single-fix rebuild: one misread sentence must be
re-recorded on its own sentence, never by rebuilding the
whole timeline.

Clean-room restatement of the method described in the Renoise
talkback review (see ``DIGITAL_HOST_IMPROVEMENT_ATTRIBUTION.md``).
This gate judges the shape of an edit declaration only; it
never opens an editor and never renders a frame.
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


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_talkback_edit(plan: Any) -> dict[str, Any]:
    """Validate a talkback edit declaration.

    Verdicts are ``pass`` / ``fail`` only. The plan fails when
    it is not an object, when silence is not removed, when
    subtitles are not aligned, when no cutaway stills are
    inserted, when a single misread sentence is not
    re-recorded on its own, or when a single fix rebuilds the
    whole timeline.
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
    if plan.get("removes_silence") is not True:
        return fail(
            "silence_not_removed",
            "dead silence must be cut from the talkback",
        )
    if plan.get("subtitles_aligned") is not True:
        return fail(
            "subtitles_not_aligned",
            "subtitles must be aligned to the speech",
        )
    if plan.get("inserts_broll") is not True:
        return fail(
            "broll_not_inserted",
            "cutaway stills must be inserted where the talk names a concrete step",
        )
    if plan.get("single_sentence_re_record") is not True:
        return fail(
            "single_sentence_re_record_missing",
            "one misread sentence must be re-recorded on its own sentence",
        )
    if plan.get("full_timeline_rebuild_on_single_fix") is True:
        return fail(
            "single_fix_rebuilds_timeline",
            "a single fix must never rebuild the whole timeline",
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
    report = check_talkback_edit(params.get("plan"))
    report_path = out_dir / "talkback_edit_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_talkback_edit_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.talkback_edit_gate",
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
                "talkback edit gate: silence cut, subtitles aligned, "
                "cutaway stills inserted, one misread sentence "
                "re-recorded on its own, never a full rebuild."
            ),
        )
    )
    return ["qa.talkback_edit_gate"]


__all__ = [
    "check_talkback_edit",
    "register_talkback_edit_gate_capabilities_once",
]
