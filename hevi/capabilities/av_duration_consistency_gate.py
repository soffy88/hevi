"""Audio/video duration consistency gate (``qa.av_duration_consistency_gate``).

Clean-room rewrite of the discipline in ``hevi-vs-digital-human-koubo-recheck.md``
item A4: for every segment, the audio duration and the video
duration must agree within a tolerance the caller supplies. The
tolerance is never invented here: when no tolerance is given for
a segment -- neither on the segment nor on the plan -- that
segment is reported ``not_checked`` in the ``qa.verdict_vocabulary``
sense, never silently passed. Overall verdicts follow the same
vocabulary: any ``fail`` fails the report, otherwise any
``not_checked`` keeps it ``not_checked``, otherwise it passes.

Drift must leave a repair chain. When the original durations
differ by more than the tolerance, the segment must carry a
``drift_repair`` record showing the durations before and after
the repair, and the repaired durations must agree within the
tolerance. A drift with no repair chain fails, and a repair
chain without the before/after comparison fails. The effective
durations judged are the repaired ones when a repair chain is
present.

This module judges duration records only. It never measures
media, never pads audio, and never re-encodes anything.
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
from hevi.capabilities.verdict_vocabulary import summarise_verdicts

_Registered = False


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.av_duration_consistency_gate: {detail}"}
    issue.update(extra)
    return issue


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_segment(entry: Any, plan_tolerance: Any) -> dict[str, Any]:
    """Judge one segment. Returns ``{segment_id, verdict, issues, ...}``."""
    issues: list[dict[str, Any]] = []
    segment_id = entry.get("segment_id") if isinstance(entry, dict) else None
    if not isinstance(entry, dict):
        return {
            "segment_id": None,
            "verdict": "fail",
            "issues": [_issue("segment_invalid", "each segment must be an object")],
        }
    if not isinstance(segment_id, str) or not segment_id.strip():
        issues.append(_issue(
            "segment_id_missing", "each segment must carry a non-empty segment_id",
        ))
    tolerance = entry.get("tolerance_s", plan_tolerance)
    if not _is_number(tolerance) or float(tolerance) < 0:
        return {
            "segment_id": segment_id,
            "verdict": "not_checked",
            "tolerance_s": None,
            "issues": [_issue(
                "tolerance_missing",
                f"segment {segment_id!r} has no caller-supplied tolerance; "
                "duration agreement is not_checked, never assumed",
                segment_id=segment_id,
            )],
        }
    tolerance = float(tolerance)
    audio = entry.get("audio_duration_s")
    video = entry.get("video_duration_s")
    if not _is_number(audio) or float(audio) < 0 \
            or not _is_number(video) or float(video) < 0:
        issues.append(_issue(
            "duration_invalid",
            f"segment {segment_id!r} needs non-negative numeric "
            "audio_duration_s and video_duration_s",
            segment_id=segment_id,
        ))
        return {
            "segment_id": segment_id,
            "verdict": "fail",
            "tolerance_s": tolerance,
            "issues": issues,
        }
    audio = float(audio)
    video = float(video)
    original_drift = abs(audio - video)
    repair = entry.get("drift_repair")
    effective_audio, effective_video = audio, video
    if repair is not None:
        if not isinstance(repair, dict):
            issues.append(_issue(
                "drift_repair_invalid",
                f"segment {segment_id!r} drift_repair must be an object",
                segment_id=segment_id,
            ))
        else:
            before_audio = repair.get("audio_before_s")
            after_audio = repair.get("audio_after_s")
            before_video = repair.get("video_before_s")
            after_video = repair.get("video_after_s")
            if not all(_is_number(v) and float(v) >= 0 for v in (
                    before_audio, after_audio, before_video, after_video)):
                issues.append(_issue(
                    "drift_repair_comparison_missing",
                    f"segment {segment_id!r} drift_repair must carry the "
                    "before/after durations for both audio and video",
                    segment_id=segment_id,
                ))
            else:
                if float(before_audio) != audio or float(before_video) != video:
                    issues.append(_issue(
                        "drift_repair_before_mismatch",
                        f"segment {segment_id!r} drift_repair before "
                        "durations must match the segment durations",
                        segment_id=segment_id,
                    ))
                effective_audio = float(after_audio)
                effective_video = float(after_video)
    effective_drift = abs(effective_audio - effective_video)
    if original_drift > tolerance and repair is None:
        issues.append(_issue(
            "drift_repair_chain_missing",
            f"segment {segment_id!r} drifts by {original_drift}s, over "
            f"the {tolerance}s tolerance, with no drift_repair chain",
            segment_id=segment_id,
            drift_s=original_drift,
        ))
    if effective_drift > tolerance:
        issues.append(_issue(
            "av_duration_mismatch",
            f"segment {segment_id!r} audio/video differ by "
            f"{effective_drift}s, over the {tolerance}s tolerance",
            segment_id=segment_id,
            drift_s=effective_drift,
        ))
    return {
        "segment_id": segment_id,
        "verdict": "pass" if not issues else "fail",
        "tolerance_s": tolerance,
        "audio_duration_s": effective_audio,
        "video_duration_s": effective_video,
        "drift_s": effective_drift,
        "issues": issues,
    }


def check_av_duration_consistency(plan: Any) -> dict[str, Any]:
    """Judge one plan. Returns a report; never raises for a bad plan."""
    if not isinstance(plan, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "segments": [],
            "issues": [_issue("plan_not_object", "plan must be an object")],
        }
    segments = plan.get("segments")
    if not isinstance(segments, list) or not segments:
        return {
            "ok": False,
            "verdict": "fail",
            "segments": [],
            "issues": [_issue(
                "segments_missing", "segments must be a non-empty list",
            )],
        }
    checked = [_check_segment(entry, plan.get("tolerance_s")) for entry in segments]
    items = [{"verdict": c["verdict"]} for c in checked]
    summary = summarise_verdicts(items)
    issues: list[dict[str, Any]] = []
    for entry in checked:
        issues.extend(entry["issues"])
    return {
        "ok": summary["verdict"] == "pass",
        "verdict": summary["verdict"],
        "counts": summary["counts"],
        "segments": checked,
        "issues": issues,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            **_kwargs: Any) -> CapabilityResult:
    report = check_av_duration_consistency(params.get("plan"))
    report_path = Path(out_dir) / "av_duration_consistency_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_av_duration_consistency_gate_capabilities_once() -> list[str]:
    """Register ``qa.av_duration_consistency_gate`` (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.av_duration_consistency_gate",
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
                "Audio/video duration consistency gate: per-segment "
                "audio and video durations must agree within a "
                "caller-supplied tolerance (missing tolerance is "
                "not_checked); drift must carry a before/after repair "
                "chain. Judges duration records only."
            ),
            line="qa",
        )
    )
    return ["qa.av_duration_consistency_gate"]


register_av_duration_consistency_gate_capabilities_once()
