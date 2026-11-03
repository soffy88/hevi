"""Motion beat chart and still-picture gate (``video.motion_beat_chart``).

A beat chart is the plan a renderer actually needs, written before
any frame is drawn. Each beat carries its time window, the action
it performs, the moving subject, the on-screen state change, the
camera, the on-screen text and the asset it uses. The chart also
carries one motion thesis up front: which visual metaphor carries
the film from its opening state to its closing state, and what
claim that movement is meant to prove. A chart with no thesis is
a pile of cards, not a moving picture.

The gate is the point. A beat whose only change is a fade or a
slide does not count as movement: cards fading in one after
another are a slideshow, however smooth the fade. At least 80% of
beats must show a real on-screen state change -- growth, gathering,
collapse, a path being drawn, a replacement, a morph, a lighting
change, a move, a zoom, a rotation -- or the whole chart goes
back for re-planning. Beats that fail are named, with the reason.

This module plans and gates only. It does not render frames:
``video.code_render`` already renders deterministic frames,
Manim and Blender already render scenes, and ``prompt_compiler``
already checks prompts. The chart's downstream export is plain
data those renderers can consume (time window, mover, change,
camera, text, asset per beat); nothing here duplicates a renderer,
a prompt checker or ``shot_continuity``'s boundary logic.
"""

from __future__ import annotations

import json
import re
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

MIN_REAL_CHANGE_RATIO = 0.80
# Changes that do NOT count as real movement on their own.
NON_REAL_CHANGES = {"fade_in", "slide_in", "fade", "slide", "static", "none", ""}
REAL_CHANGES = {
    "grow", "gather", "collapse", "draw_path", "replace", "morph",
    "light_up", "move", "zoom", "rotate", "split", "merge",
    "reveal", "assemble", "scatter", "spin", "bounce", "flow",
}
_BEAT_FIELDS = ("start_sec", "end_sec", "action", "mover", "state_change",
                "camera", "text", "asset", "change_kind")
_EMOJI_RE = re.compile(
    "["
    "\U0001f000-\U0001faff"
    "\U00002600-\U000027bf"
    "\U0001f1e6-\U0001f1ff"
    "\uFE0F"
    "]"
)


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_thesis(thesis: dict[str, Any] | None) -> list[str]:
    """A thesis needs a metaphor, a start state, an end state and a claim."""
    problems: list[str] = []
    if not isinstance(thesis, dict):
        return ["motion thesis missing: a chart needs one sentence of movement logic"]
    for field in ("visual_metaphor", "from_state", "to_state", "claim"):
        value = thesis.get(field)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"motion thesis field {field!r} is missing or empty")
    return problems


def validate_beat(beat: dict[str, Any], index: int) -> list[str]:
    """Check one beat's completeness; return its problems, if any."""
    problems: list[str] = []
    if not isinstance(beat, dict):
        return [f"beat {index} must be an object"]
    for field in _BEAT_FIELDS:
        if field not in beat:
            problems.append(f"beat {index} missing field {field!r}")
    start, end = beat.get("start_sec"), beat.get("end_sec")
    if _is_num(start) and _is_num(end):
        if float(start) < 0 or float(end) <= float(start):
            problems.append(f"beat {index} has an invalid time window ({start} to {end})")
    else:
        problems.append(f"beat {index} needs numeric start_sec/end_sec")
    for field in ("action", "mover", "state_change", "camera", "change_kind"):
        value = beat.get(field)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"beat {index} field {field!r} is missing or empty")
    for field in ("text", "asset"):
        if field in beat and not isinstance(beat[field], str):
            problems.append(f"beat {index} field {field!r} must be a string")
    change_kind = beat.get("change_kind")
    if isinstance(change_kind, str) and change_kind:
        if change_kind not in REAL_CHANGES and change_kind not in NON_REAL_CHANGES:
            problems.append(f"beat {index} unknown change_kind {change_kind!r}")
    text = beat.get("text", "")
    if isinstance(text, str) and _EMOJI_RE.search(text):
        problems.append(f"beat {index} text contains a pictograph, which is banned")
    return problems


def gate_chart(chart: dict[str, Any]) -> dict[str, Any]:
    """Gate a whole chart: completeness, thesis, real-change ratio."""
    if not isinstance(chart, dict):
        raise CapabilityError("video.motion_beat_chart: chart must be an object")
    beats = chart.get("beats")
    if not isinstance(beats, list) or not beats:
        raise CapabilityError("video.motion_beat_chart: beats must be a non-empty list")
    problems: list[dict[str, Any]] = []
    thesis_problems = validate_thesis(chart.get("thesis"))
    for p in thesis_problems:
        problems.append({"beat": None, "kind": "thesis", "detail": p})
    beat_problems: list[dict[str, Any]] = []
    real = 0
    non_real_beats: list[int] = []
    for i, beat in enumerate(beats):
        for p in validate_beat(beat, i):
            beat_problems.append({"beat": i, "kind": "beat_incomplete", "detail": p})
        if isinstance(beat, dict):
            kind = beat.get("change_kind")
            if kind in REAL_CHANGES:
                real += 1
            elif kind in NON_REAL_CHANGES:
                non_real_beats.append(i)
    ratio = real / len(beats)
    if ratio < MIN_REAL_CHANGE_RATIO:
        problems.append({
            "beat": None, "kind": "anti_still_picture",
            "detail": f"only {real}/{len(beats)} beats show a real state change "
            f"(ratio {ratio:.2f}, floor {MIN_REAL_CHANGE_RATIO:.2f}); "
            f"fade/slide-only beats: {non_real_beats}",
        })
    all_problems = problems + beat_problems
    return {
        "capability": "video.motion_beat_chart",
        "beat_count": len(beats),
        "real_change_count": real,
        "real_change_ratio": round(ratio, 3),
        "min_real_change_ratio": MIN_REAL_CHANGE_RATIO,
        "non_real_beats": non_real_beats,
        "problems": all_problems,
        "verdict": "fail" if all_problems else "pass",
    }


def to_downstream_plan(chart: dict[str, Any]) -> dict[str, Any]:
    """Export a gated chart as plain data for code_render/Manim/Blender.

    No rendering happens here: each beat becomes one downstream
    item (time window, mover, change, camera, text, asset) that a
    renderer can turn into frames. An ungated chart is still
    exportable, but the export carries its verdict so a downstream
    step can refuse a failed chart instead of rendering it blind.
    """
    gate = gate_chart(chart)
    beats = chart.get("beats") if isinstance(chart, dict) else []
    items = []
    for beat in beats or []:
        if not isinstance(beat, dict):
            continue
        items.append({
            "start_sec": beat.get("start_sec"),
            "end_sec": beat.get("end_sec"),
            "mover": beat.get("mover"),
            "change": beat.get("state_change"),
            "change_kind": beat.get("change_kind"),
            "camera": beat.get("camera"),
            "text": beat.get("text", ""),
            "asset": beat.get("asset", ""),
            "action": beat.get("action"),
        })
    thesis = chart.get("thesis") if isinstance(chart, dict) else None
    return {
        "thesis": thesis,
        "gate_verdict": gate["verdict"],
        "beats": items,
        "note": "Downstream renderers (video.code_render, Manim, Blender) "
        "consume beats as time-windowed mover/change items; this "
        "export renders nothing itself.",
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    chart = params.get("chart")
    if not isinstance(chart, dict):
        raise CapabilityError("video.motion_beat_chart: chart must be an object")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = gate_chart(chart)
    report["downstream_plan"] = to_downstream_plan(chart)
    report_path = out_dir / "motion_beat_chart_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"],
            "real_change_ratio": report["real_change_ratio"]},
    )


def register_motion_beat_chart_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.motion_beat_chart",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {"chart": {"type": "object"}},
                "required": ["chart"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Motion beat chart and still-picture gate: every beat "
                "carries time, action, mover, state change, camera, "
                "text, asset and change kind, plus one motion thesis "
                "(metaphor, start state, end state, claim). At least "
                "80% of beats must show a real state change beyond "
                "fade/slide, or the chart is returned for re-planning. "
                "Exports a plain downstream plan for code_render, "
                "Manim or Blender; renders nothing itself."
            ),
            line="video",
        )
    )
    return ["video.motion_beat_chart"]


register_motion_beat_chart_capabilities_once()
