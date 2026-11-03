"""Voice-first timing gate (``qa.vo_first_timing_gate``).

Clean-room restatement of the method in ``hevi-vs-explainer-skills-9.md``
section 2 item 4 (Vox) and item 7 (iart): the measured narration is
the master clock of the film. Pictures adapt to the voice; the voice
is never squeezed to fit the pictures. In hevi's caliber:

1. A narration evidence record must be present, with a measured
   duration in seconds and an evidence identifier. The evidence shape
   reuses the ``audio.asr_transcribe`` record caliber (transcript plus
   measured duration); an estimated duration is not evidence.
2. Every beat must tile the measured narration exactly -- beats run
   back to back from 0 to the measured duration, with no gap and no
   overlap beyond a 1ms rounding tolerance -- and every beat must
   declare that it derives from the narration.

This module judges plans only. It reads no audio bytes and calls no
transcriber; the caller supplies the evidence record.
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

_EPS = 0.001


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_vo_first_timing(plan: Any) -> dict[str, Any]:
    """Judge one voice-first timing plan. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only.
    """
    issues: list[dict[str, Any]] = []
    beats_out: list[dict[str, Any]] = []
    measured: float | None = None
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("plan_not_object", "timing plan must be a JSON object")],
            "measured_duration_s": None,
            "beats": [],
        }
    narration = plan.get("narration")
    if not isinstance(narration, dict):
        issues.append(
            _issue(
                "narration_missing",
                "plan must carry a narration evidence record",
            )
        )
    else:
        if "estimated_duration_s" in narration:
            issues.append(
                _issue(
                    "estimated_timing",
                    "an estimated narration duration is not measured evidence",
                )
            )
        duration = narration.get("measured_duration_s")
        if not _is_number(duration) or duration <= 0:
            issues.append(
                _issue(
                    "measured_duration_missing",
                    "narration must declare a positive measured_duration_s",
                )
            )
        else:
            measured = float(duration)
        if not _is_nonempty_str(narration.get("evidence_id")):
            issues.append(
                _issue(
                    "narration_evidence_missing",
                    "narration must carry an evidence_id",
                )
            )
    beats = plan.get("beats")
    if not isinstance(beats, list) or not beats:
        issues.append(_issue("beats_missing", "plan must declare a non-empty beats list"))
        beats = beats if isinstance(beats, list) else []
    cursor = 0.0
    for index, beat in enumerate(beats):
        if not isinstance(beat, dict):
            issues.append(
                _issue("beat_not_object", f"beats[{index}] must be an object")
            )
            continue
        start = beat.get("start_s")
        end = beat.get("end_s")
        if not _is_number(start) or not _is_number(end) or end <= start:
            issues.append(
                _issue(
                    "beat_window_invalid",
                    f"beats[{index}] must declare start_s < end_s",
                )
            )
            continue
        if abs(float(start) - cursor) > _EPS:
            issues.append(
                _issue(
                    "beat_gap_or_overlap",
                    f"beats[{index}] starts at {start}, expected {cursor} "
                    "for gapless tiling",
                )
            )
        if beat.get("derived_from") != "narration":
            issues.append(
                _issue(
                    "beat_not_derived_from_narration",
                    f"beats[{index}] must declare derived_from='narration'",
                )
            )
        beats_out.append(
            {"id": beat.get("id"), "start_s": start, "end_s": end}
        )
        cursor = float(end)
    if measured is not None and beats_out:
        if abs(cursor - measured) > _EPS:
            issues.append(
                _issue(
                    "beats_do_not_cover_narration",
                    f"beats end at {cursor}, narration measures {measured}",
                )
            )
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "ok": verdict == "pass",
        "issues": issues,
        "measured_duration_s": measured,
        "beats": beats_out,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_vo_first_timing(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "vo_first_timing_gate_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "ok": report["ok"],
        },
    )


def register_vo_first_timing_gate_capabilities_once() -> list[str]:
    """Register ``qa.vo_first_timing_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.vo_first_timing_gate",
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
                "Voice-first timing gate: the measured narration duration is "
                "the master clock; beats must tile it gaplessly and declare "
                "that they derive from the narration. Estimated durations "
                "are not evidence. Plans are judged, never retimed."
            ),
            line="qa",
        )
    )
    return ["qa.vo_first_timing_gate"]


register_vo_first_timing_gate_capabilities_once()
