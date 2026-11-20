"""Preview-to-video five-segment gate (``qa.preview_video_five_segment_gate``).

A preview-first film has five segments and one timeline:
intro 30s, three chapters of 60s each, outro 30s, 240s in
total. The composition carries a ``data-composition-id``.
Exactly one GSAP timeline is mounted at
``window.__timelines['main']``. The video version plays
automatically and carries no interactive controls: no
sliders, no OrbitControls, no buttons or inputs of any
kind. The interactive preview may have controls; the video
must not.

When the film enters the teaching line, provenance comes
first: the plan must name the already-registered
per-sentence source ledger gate (``qa.source_sentence_ledger``,
``check_source_sentence_ledger`` in
``hevi/capabilities/source_sentence_ledger.py``) and record
that it passed. There is no ``citation_check`` capability in
hevi; that name must not be cited as a gate. See
``AETHERVIZ_G4_G5_ATTRIBUTION.md``.

This gate judges structure declarations only; it never
generates HTML, never renders video, and never copies text
or code from any outside repository.
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

SEGMENT_DURATIONS: tuple[int, ...] = (30, 60, 60, 60, 30)
TOTAL_DURATION_S = 240
TIMELINE_MOUNT = "window.__timelines['main']"
PROVENANCE_GATE = "qa.source_sentence_ledger"


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check_preview_video_five_segment(plan: Any) -> dict[str, Any]:
    """Validate one preview-to-video five-segment plan.

    ``plan`` carries ``composition_id`` (the
    ``data-composition-id`` value), ``segments`` (five
    ``{id, duration_s}`` entries of 30/60/60/60/30),
    ``timeline`` (``{single: true, mount}``), ``video``
    (``{autoplay: true, interactive_controls: []}``), and,
    when ``teaching_line`` is true, ``provenance`` (``{gate,
    source_ledger_passed}``). Returns a report; never raises.
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
    if not _is_nonempty_str(plan.get("composition_id")):
        return fail(
            "composition_id_missing",
            "composition_id (data-composition-id) must be a non-empty string",
        )
    segments = plan.get("segments")
    if not isinstance(segments, list) or len(segments) != 5:
        return fail(
            "segment_count_wrong",
            "exactly five segments are required (intro, three chapters, outro)",
        )
    durations: list[Any] = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            return fail(
                "segment_not_object",
                f"segments[{index}] must be an object",
            )
        if not _is_nonempty_str(segment.get("id")):
            return fail(
                "segment_id_missing",
                f"segments[{index}] must carry a non-empty id",
            )
        durations.append(segment.get("duration_s"))
    if durations != list(SEGMENT_DURATIONS):
        return fail(
            "segment_duration_wrong",
            f"segment durations must be {list(SEGMENT_DURATIONS)} seconds, got {durations}",
        )
    if sum(durations) != TOTAL_DURATION_S:
        return fail(
            "total_duration_wrong",
            f"segments must sum to {TOTAL_DURATION_S} seconds",
        )
    timeline = plan.get("timeline")
    if not isinstance(timeline, dict) or timeline.get("single") is not True:
        return fail(
            "timeline_not_single",
            "exactly one GSAP timeline is required",
        )
    if timeline.get("mount") != TIMELINE_MOUNT:
        return fail(
            "timeline_mount_wrong",
            f"the single timeline must mount at {TIMELINE_MOUNT!r}",
        )
    video = plan.get("video")
    if not isinstance(video, dict):
        return fail(
            "video_missing",
            "video must be an object with autoplay and interactive_controls",
        )
    if video.get("autoplay") is not True:
        return fail(
            "autoplay_off",
            "the video version must play automatically",
        )
    controls = video.get("interactive_controls")
    if not isinstance(controls, list):
        return fail(
            "interactive_controls_invalid",
            "interactive_controls must be a list",
        )
    if controls:
        return fail(
            "interactive_control_in_video",
            f"the video version must carry no interactive controls, got {controls}",
        )
    if plan.get("teaching_line") is True:
        provenance = plan.get("provenance")
        if (
            not isinstance(provenance, dict)
            or provenance.get("gate") != PROVENANCE_GATE
            or provenance.get("source_ledger_passed") is not True
        ):
            return fail(
                "teaching_provenance_missing",
                "a film entering the teaching line must first pass "
                f"the {PROVENANCE_GATE} source ledger and record it "
                "in provenance (gate + source_ledger_passed=true)",
            )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
        "segment_count": 5,
        "total_duration_s": TOTAL_DURATION_S,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_preview_video_five_segment(params.get("plan"))
    report_path = out_dir / "preview_video_five_segment_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_preview_video_five_segment_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.preview_video_five_segment_gate",
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
                "preview-to-video five-segment gate: 30+60+60+60+30 "
                "= 240s, data-composition-id required, one GSAP "
                "timeline at window.__timelines['main'], video "
                "autoplays with no interactive controls, teaching-line "
                "films first pass the source sentence ledger."
            ),
        )
    )
    return ["qa.preview_video_five_segment_gate"]


__all__ = [
    "PROVENANCE_GATE",
    "SEGMENT_DURATIONS",
    "TIMELINE_MOUNT",
    "TOTAL_DURATION_S",
    "check_preview_video_five_segment",
    "register_preview_video_five_segment_gate_capabilities_once",
]
