"""Hand-painted narration alignment plan (``animation.handpaint_narration_align``).

Clean-room method intake, written from the method description only.
It complements ``animation.handpaint_anim`` (which plans guides, camera
and brush wipes) without duplicating it: this module owns the one thing
handpaint_anim does not do -- narration-first, frame-level alignment of
a hand-drawn sequence.

Method, in order:
* Narration comes first. Every narration line carries absolute
  start/end seconds; every drawing event is scheduled inside the
  window of the narration line it illustrates. Nothing is scheduled
  before narration starts or after it ends.
* Stroke order inside one drawn element is fixed: outline strokes
  first, then diagonal-hatch fill strokes, then detail strokes.
  An element whose strokes arrive in any other phase order is
  rejected, not silently re-sorted, so a bad storyboard fails loudly.
* Fill, when present, is diagonal hatching only: the hatch angle
  must be genuinely diagonal (not horizontal, not vertical).
* Camera moves and transitions come from closed catalogues, and
  their windows must lie inside the overall narration span.

Scope, stated honestly in the output: this is a plan only. It
renders no frames, no video and no audio; a renderer consumes the
cue sheet (stroke events with frame numbers and seconds). No
VoxCPM-style model is involved and no model is called.

Failure contract: empty narration, unsorted or overlapping
narration lines, a stroke phase out of order, a non-diagonal hatch
angle, an unknown camera/transition kind, a reference to an unknown
narration line or element, or a camera/transition window outside
the narration span all raise CapabilityError.
"""

from __future__ import annotations

import json
import math
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
_TOL = 1e-9
_PHASE_RANK = {"outline": 0, "hatch": 1, "detail": 2}
_CAMERA_KINDS = (
    "static",
    "push_in",
    "pull_out",
    "pan_left",
    "pan_right",
    "tilt_up",
    "tilt_down",
    "zoom_to_detail",
)
_TRANSITION_KINDS = ("cut", "fade", "dissolve", "wipe_brush", "morph")


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_num(value: Any, what: str) -> float:
    if not _is_num(value):
        raise CapabilityError(f"animation.handpaint_narration_align: {what} must be a number")
    return float(value)


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(f"animation.handpaint_narration_align: {what} must be a non-empty string")
    return value.strip()


def _require_int(value: Any, what: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise CapabilityError(f"animation.handpaint_narration_align: {what} must be an integer")
    return value


def build_narration_plan(plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise CapabilityError("animation.handpaint_narration_align: plan must be a JSON object")
    fps = plan.get("fps", 24)
    fps = _require_int(fps, "fps")
    if fps < 1 or fps > 120:
        raise CapabilityError("animation.handpaint_narration_align: fps must be between 1 and 120")
    narration_raw = plan.get("narration")
    if not isinstance(narration_raw, list) or not narration_raw:
        raise CapabilityError("animation.handpaint_narration_align: narration must be a non-empty list")
    narration: list[dict[str, Any]] = []
    prev_end = -1.0
    for i, line in enumerate(narration_raw):
        if not isinstance(line, dict):
            raise CapabilityError(f"animation.handpaint_narration_align: narration line {i} must be a JSON object")
        lid = _require_str(line.get("id"), f"narration line {i}.id")
        if any(n["id"] == lid for n in narration):
            raise CapabilityError(f"animation.handpaint_narration_align: duplicate narration id {lid!r}")
        text = _require_str(line.get("text"), f"narration line {i}.text")
        start = _require_num(line.get("start_sec"), f"narration line {i}.start_sec")
        end = _require_num(line.get("end_sec"), f"narration line {i}.end_sec")
        if start < 0 or end <= start:
            raise CapabilityError(f"animation.handpaint_narration_align: narration line {i} has an invalid time range")
        if start < prev_end - _TOL:
            raise CapabilityError("animation.handpaint_narration_align: narration lines must be sorted and non-overlapping")
        prev_end = end
        narration.append({"id": lid, "text": text, "start_sec": start, "end_sec": end})
    by_narration = {n["id"]: n for n in narration}
    span_start, span_end = narration[0]["start_sec"], narration[-1]["end_sec"]

    elements_raw = plan.get("elements", [])
    if not isinstance(elements_raw, list):
        raise CapabilityError("animation.handpaint_narration_align: elements must be a list")
    elements: list[dict[str, Any]] = []
    element_ids: set[str] = set()
    for i, el in enumerate(elements_raw):
        if not isinstance(el, dict):
            raise CapabilityError(f"animation.handpaint_narration_align: element {i} must be a JSON object")
        eid = _require_str(el.get("id"), f"element {i}.id")
        if eid in element_ids:
            raise CapabilityError(f"animation.handpaint_narration_align: duplicate element id {eid!r}")
        element_ids.add(eid)
        nid = _require_str(el.get("narration_id"), f"element {i}.narration_id")
        if nid not in by_narration:
            raise CapabilityError(f"animation.handpaint_narration_align: element {eid!r} references unknown narration {nid!r}")
        strokes_raw = el.get("strokes")
        if not isinstance(strokes_raw, list) or not strokes_raw:
            raise CapabilityError(f"animation.handpaint_narration_align: element {eid!r} needs a non-empty strokes list")
        strokes: list[dict[str, Any]] = []
        seen_strokes: set[str] = set()
        last_rank = -1
        for j, st in enumerate(strokes_raw):
            if not isinstance(st, dict):
                raise CapabilityError(f"animation.handpaint_narration_align: element {eid!r} stroke {j} must be a JSON object")
            sid = _require_str(st.get("id"), f"element {eid!r} stroke {j}.id")
            if sid in seen_strokes:
                raise CapabilityError(f"animation.handpaint_narration_align: element {eid!r} duplicate stroke id {sid!r}")
            seen_strokes.add(sid)
            phase = st.get("phase")
            if phase not in _PHASE_RANK:
                raise CapabilityError(
                    f"animation.handpaint_narration_align: element {eid!r} stroke {sid!r} phase must be outline/hatch/detail"
                )
            rank = _PHASE_RANK[phase]
            if rank < last_rank:
                raise CapabilityError(
                    f"animation.handpaint_narration_align: element {eid!r} stroke order violates outline-then-hatch-then-detail"
                )
            last_rank = rank
            strokes.append({"id": sid, "phase": phase})
        fill = el.get("fill")
        fill_out = None
        if fill is not None:
            if not isinstance(fill, dict):
                raise CapabilityError(f"animation.handpaint_narration_align: element {eid!r} fill must be a JSON object")
            method = fill.get("method")
            if method != "diagonal_hatch":
                raise CapabilityError(f"animation.handpaint_narration_align: element {eid!r} fill method must be diagonal_hatch")
            angle = _require_num(fill.get("angle_deg"), f"element {eid!r} fill.angle_deg")
            if not (0.0 < angle < 180.0) or abs(angle - 90.0) < _TOL:
                raise CapabilityError(
                    f"animation.handpaint_narration_align: element {eid!r} hatch angle must be diagonal, not horizontal or vertical"
                )
            fill_out = {"method": "diagonal_hatch", "angle_deg": angle}
        elements.append({"id": eid, "narration_id": nid, "strokes": strokes, "fill": fill_out})

    # Narration-first frame scheduling: strokes of one element share
    # its narration line window, spread in stroke order.
    cue_sheet: list[dict[str, Any]] = []
    for line in narration:
        start_frame = int(math.floor(line["start_sec"] * fps))
        end_frame = max(start_frame, int(math.ceil(line["end_sec"] * fps)) - 1)
        line_elements = [e for e in elements if e["narration_id"] == line["id"]]
        events: list[dict[str, Any]] = []
        for el in line_elements:
            span = end_frame - start_frame + 1
            for k, st in enumerate(el["strokes"]):
                at_frame = start_frame + int(math.floor(k * span / len(el["strokes"])))
                events.append({
                    "element_id": el["id"],
                    "stroke_id": st["id"],
                    "phase": st["phase"],
                    "at_frame": at_frame,
                    "at_sec": round(at_frame / fps, 3),
                })
        cue_sheet.append({
            "narration_id": line["id"],
            "text": line["text"],
            "start_sec": line["start_sec"],
            "end_sec": line["end_sec"],
            "start_frame": start_frame,
            "end_frame": end_frame,
            "stroke_events": events,
            "crowded": any(
                len([e for e in line_elements if e["id"] == el["id"]][0]["strokes"]) > (end_frame - start_frame + 1)
                for el in line_elements
            ),
        })

    cameras: list[dict[str, Any]] = []
    for i, cam in enumerate(plan.get("camera_moves", [])):
        if not isinstance(cam, dict):
            raise CapabilityError(f"animation.handpaint_narration_align: camera move {i} must be a JSON object")
        kind = cam.get("kind")
        if kind not in _CAMERA_KINDS:
            raise CapabilityError(f"animation.handpaint_narration_align: unknown camera kind {kind!r}")
        start = _require_num(cam.get("start_sec"), f"camera move {i}.start_sec")
        end = _require_num(cam.get("end_sec"), f"camera move {i}.end_sec")
        if start < span_start - _TOL or end > span_end + _TOL or end <= start:
            raise CapabilityError(f"animation.handpaint_narration_align: camera move {i} must lie inside the narration span")
        cameras.append({"id": _require_str(cam.get("id"), f"camera move {i}.id"), "kind": kind, "start_sec": start, "end_sec": end})

    transitions: list[dict[str, Any]] = []
    for i, tr in enumerate(plan.get("transitions", [])):
        if not isinstance(tr, dict):
            raise CapabilityError(f"animation.handpaint_narration_align: transition {i} must be a JSON object")
        kind = tr.get("kind")
        if kind not in _TRANSITION_KINDS:
            raise CapabilityError(f"animation.handpaint_narration_align: unknown transition kind {kind!r}")
        at = _require_num(tr.get("at_sec"), f"transition {i}.at_sec")
        if at < span_start - _TOL or at > span_end + _TOL:
            raise CapabilityError(f"animation.handpaint_narration_align: transition {i} must lie inside the narration span")
        frm, to = tr.get("from_element"), tr.get("to_element")
        if frm is not None and frm not in element_ids:
            raise CapabilityError(f"animation.handpaint_narration_align: transition {i} references unknown element {frm!r}")
        if to is not None and to not in element_ids:
            raise CapabilityError(f"animation.handpaint_narration_align: transition {i} references unknown element {to!r}")
        transitions.append({"id": _require_str(tr.get("id"), f"transition {i}.id"), "kind": kind, "at_sec": at, "from_element": frm, "to_element": to})

    return {
        "capability": "animation.handpaint_narration_align",
        "fps": fps,
        "narration_span_sec": [span_start, span_end],
        "stroke_order_rule": "outline, then diagonal-hatch fill, then detail",
        "fill_rule": "diagonal_hatch only; angle must be diagonal, not 0/90/180",
        "elements": elements,
        "cue_sheet": cue_sheet,
        "camera_moves": cameras,
        "transitions": transitions,
        "camera_catalog": list(_CAMERA_KINDS),
        "transition_catalog": list(_TRANSITION_KINDS),
        "render_status": "plan_only_no_render",
        "render_note": "No frames, video or audio are produced here; a renderer consumes cue_sheet.",
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    result = build_narration_plan(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "handpaint_narration_align.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), "cue_lines": len(result["cue_sheet"]), "render_status": "plan_only_no_render"},
    )


def register_handpaint_narration_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="animation.handpaint_narration_align",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema={
            "type": "object",
            "properties": {"plan": {"type": "object"}},
            "required": ["plan"],
            "additionalProperties": False,
        },
        cpu_cost_hint=0.0,
        render=_render,
        has_media_output=False,
        description=(
            "Hand-painted narration alignment plan (clean-room): narration-first "
            "frame cue sheet, outline-then-diagonal-hatch-then-detail stroke order, "
            "and a closed camera/transition catalogue. Plan only, no rendering."
        ),
        line="animation",
    ))
    return ["animation.handpaint_narration_align"]


register_handpaint_narration_capabilities_once()
