"""Hand-painted animation planning capabilities (clean-room method intake).

Registers six ``animation.*`` capabilities.  This module translates the
method of JohnHeibel/ClaudeAnimationBase into hevi's Python capability
system from the method description only: no upstream code, asset,
character, image, or JS is copied, and nothing here references the
upstream mascot character (see the originality red line below).

Method elements internalised (rewritten, not ported):

* ANIMATION_GUIDE: seven deterministic rules -- unified medium, no
  on-screen text, every shot has an event, audience-time modelling,
  a living picture, every transition motivated, vision before code.
* A pure-function time/camera model: given a time ``t`` it returns a
  deterministic character/camera state (easing, pan/zoom, seeded
  boiling-linework jitter).  No RNG global state is touched.
* A shots/loops timeline structure with continuity validation.
* A brush-wipe transition specification (direction, duration, brush
  parameters) that yields an executable render plan, not a video.
* A render self-check plan: per-shot first/mid/last contact-sheet
  picks, a per-step frame strip, and a follow-the-world-point crop-at
  plan.  When real frames exist it builds a contact-sheet PNG with
  PIL; when no frames are supplied it emits the plan only and never
  fabricates an image.

Relationship to existing hevi capabilities (no reinvention):

* ``image.expression_rig`` is REUSED, not duplicated: the character
  views (front / three_quarter / profile) and emotion names used here
  are imported from ``hevi.layer4_legacy.handdraw.expression_rig``
  (``VIEWS`` / ``EMOTIONS``) at call time and validated against them.
  This module defines no view/emotion enum of its own.  The demo
  character is hevi's own original ``tuantuan``.
* ``image.brush_scene`` (brushpaint) is ALIGNED, not re-rendered:
  brush parameters here use the same vocabulary (a named scene
  template plus a seed); the demo references the bundled
  ``pond_night`` template by name and validates it against
  ``hevi.image.brushpaint.scene.list_templates``.  This module has no
  stroke renderer of its own.
* ``edit.timeline_register`` is the LANDING layer, this module is the
  PLAN layer: ``animation.timeline`` validates a shot plan *before*
  anything is rendered (continuity, loops, transitions); once a shot
  is actually rendered, the caller lands the real file on a project
  timeline with ``edit.timeline_register`` (which requires a real
  file reference and a unique clip id).  Field names are kept apart
  on purpose: plan shots use ``start_sec`` / ``end_sec`` while the
  landing layer uses ``timeline_start_sec`` / ``timeline_end_sec``.

Originality red line: no third-party character design, silhouette,
palette, asset, dance, emote, image, or JS is copied or referenced.
All characters here are hevi's own original ``tuantuan``; all renders
are hevi's own procedural code.

Failure contract: every invalid input raises ``CapabilityError``.
Missing evidence in a guide check is reported as ``pending`` (never
as a pass); a plan with no frames yields a plan only (never a fake
image).  CPU only, zero paid calls, deterministic per (plan, seed).

Registration note: this module self-registers on import (guarded,
idempotent), following the ``image.brush_scene`` precedent, and is
also wired through ``hevi/capabilities/__init__.py`` so that
``import hevi.capabilities`` is the single catalogue source.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
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
_EPS = 1e-6

GUIDE_RULES = [
    ("medium_unified", "Unified medium: every shot in one medium"),
    ("no_text", "No on-screen text"),
    ("every_shot_has_event", "Every shot has an event"),
    ("audience_time", "Audience time is modelled (durations add up)"),
    ("picture_alive", "The picture is alive (motion in every shot)"),
    ("transition_motivated", "Every transition is motivated"),
    ("vision_before_code", "Vision before code"),
]

BRUSH_WIPE_DIRECTIONS = (
    "left_to_right",
    "right_to_left",
    "top_to_bottom",
    "bottom_to_top",
    "diagonal_down_right",
    "diagonal_down_left",
)

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_dict(value: Any, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CapabilityError(f"animation: {what} must be a JSON object")
    return value


def _write_json(out_dir: Path, name: str, payload: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def _result_for_report(
    report_path: Path, payload: dict[str, Any], extra_qa: dict[str, Any] | None = None
) -> CapabilityResult:
    qa: dict[str, Any] = {"report_json": str(report_path), **payload}
    if extra_qa:
        qa.update(extra_qa)
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa=qa,
    )


def _expression_enums() -> tuple[list[str], list[str]]:
    """Views/emotions borrowed from expression_rig (never redefined here)."""
    from hevi.layer4_legacy.handdraw.expression_rig import EMOTIONS, VIEWS

    return list(VIEWS), sorted(EMOTIONS)


def _brush_templates() -> list[str] | None:
    try:
        from hevi.image.brushpaint.scene import list_templates

        return list_templates()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 1. Guide check: ANIMATION_GUIDE seven rules, deterministic
# ---------------------------------------------------------------------------

def _rule(status: str, evidence: str, detail: str) -> dict[str, Any]:
    return {"status": status, "evidence": evidence, "detail": detail}


def check_guide(plan: dict[str, Any]) -> dict[str, Any]:
    """Check one animation plan against the seven guide rules.

    Status vocabulary: ``pass`` / ``pending`` / ``fail``.  A rule with
    no evidence in the plan is ``pending`` -- it is never reported as
    a pass.  A rule whose evidence contradicts it is ``fail``.
    """
    plan = _require_dict(plan, "plan")
    shots = plan.get("shots")
    if shots is not None and not isinstance(shots, list):
        raise CapabilityError("animation.guide_check: plan.shots must be a list")
    shots = shots or []
    results: dict[str, Any] = {}

    # R1: unified medium.
    medium = plan.get("medium")
    if medium is None and not shots:
        results["medium_unified"] = _rule("pending", "plan.medium", "no medium declared and no shots")
    elif not isinstance(medium, str) or not medium.strip():
        results["medium_unified"] = _rule("fail", "plan.medium", "medium must be a non-empty string")
    else:
        mismatched = [s.get("shot_id") for s in shots
                      if isinstance(s, dict) and s.get("medium") not in (None, medium)]
        if mismatched:
            results["medium_unified"] = _rule("fail", "shot.medium", f"shots diverge from plan medium: {mismatched}")
        else:
            results["medium_unified"] = _rule("pass", "plan.medium", f"medium={medium!r} shared by {len(shots)} shot(s)")

    # R2: no on-screen text.
    if not shots:
        results["no_text"] = _rule("pending", "shot.has_text", "no shots to check")
    else:
        bad: list[str] = []
        missing: list[str] = []
        for shot in shots:
            if not isinstance(shot, dict):
                raise CapabilityError("animation.guide_check: each shot must be an object")
            sid = str(shot.get("shot_id") or "?")
            if "has_text" not in shot and "text_elements" not in shot:
                missing.append(sid)
            elif shot.get("has_text") is True or shot.get("text_elements"):
                bad.append(sid)
        if bad:
            results["no_text"] = _rule("fail", "shot.has_text/text_elements", f"text present in shots: {bad}")
        elif missing:
            results["no_text"] = _rule("pending", "shot.has_text", f"text evidence missing for shots: {missing}")
        else:
            results["no_text"] = _rule("pass", "shot.has_text=false", "no shot declares text")

    # R3: every shot has an event.
    if not shots:
        results["every_shot_has_event"] = _rule("pending", "shot.event", "no shots to check")
    else:
        bad, missing = [], []
        for shot in shots:
            sid = str(shot.get("shot_id") or "?")
            event = shot.get("event", shot.get("action"))
            if event is None:
                missing.append(sid)
            elif not isinstance(event, str) or not event.strip():
                bad.append(sid)
        if bad:
            results["every_shot_has_event"] = _rule("fail", "shot.event", f"empty event in shots: {bad}")
        elif missing:
            results["every_shot_has_event"] = _rule("pending", "shot.event", f"event missing for shots: {missing}")
        else:
            results["every_shot_has_event"] = _rule("pass", "shot.event", "every shot declares a non-empty event")

    # R4: audience time modelled -- durations present, positive, summing.
    if not shots:
        results["audience_time"] = _rule("pending", "shot.duration_sec", "no shots to check")
    else:
        bad, missing = [], []
        total = 0.0
        for shot in shots:
            sid = str(shot.get("shot_id") or "?")
            dur = shot.get("duration_sec")
            if dur is None and _is_num(shot.get("start_sec")) and _is_num(shot.get("end_sec")):
                dur = float(shot["end_sec"]) - float(shot["start_sec"])
            if dur is None:
                missing.append(sid)
            elif not _is_num(dur) or float(dur) <= 0:
                bad.append(sid)
            else:
                total += float(dur)
        declared = plan.get("total_duration_sec", plan.get("total_sec"))
        if bad:
            results["audience_time"] = _rule("fail", "shot.duration_sec", f"non-positive duration in shots: {bad}")
        elif missing:
            results["audience_time"] = _rule("pending", "shot.duration_sec", f"duration missing for shots: {missing}")
        elif declared is not None and (not _is_num(declared) or abs(float(declared) - total) > 1e-6):
            results["audience_time"] = _rule("fail", "plan.total_duration_sec", f"declared total {declared} != shot sum {total}")
        else:
            results["audience_time"] = _rule("pass", "shot.duration_sec sum", f"shot durations sum to {total} s")

    # R5: picture alive -- motion in every shot.
    if not shots:
        results["picture_alive"] = _rule("pending", "shot.motion", "no shots to check")
    else:
        bad, missing = [], []
        for shot in shots:
            sid = str(shot.get("shot_id") or "?")
            motion = shot.get("motion")
            if motion is None:
                missing.append(sid)
            elif not isinstance(motion, list) or not motion:
                bad.append(sid)
        if bad:
            results["picture_alive"] = _rule("fail", "shot.motion", f"no motion in shots: {bad}")
        elif missing:
            results["picture_alive"] = _rule("pending", "shot.motion", f"motion missing for shots: {missing}")
        else:
            results["picture_alive"] = _rule("pass", "shot.motion", "every shot declares motion")

    # R6: every transition motivated.
    transitions = plan.get("transitions")
    if not shots or len(shots) < 2:
        results["transition_motivated"] = _rule("pass", "transitions", "fewer than 2 shots, no transition needed")
    elif transitions is None:
        results["transition_motivated"] = _rule("pending", "plan.transitions", "transitions not declared")
    elif not isinstance(transitions, list):
        raise CapabilityError("animation.guide_check: plan.transitions must be a list")
    else:
        covered: set[str] = set()
        bad: list[str] = []
        for tr in transitions:
            if not isinstance(tr, dict):
                raise CapabilityError("animation.guide_check: each transition must be an object")
            target = str(tr.get("to_shot") or tr.get("to") or "")
            reason = tr.get("reason")
            if target:
                covered.add(target)
            if not isinstance(reason, str) or not reason.strip():
                bad.append(target or "?")
        needed = {str(s.get("shot_id")) for s in shots[1:] if isinstance(s, dict)}
        unmotivated = sorted(needed - covered)
        if unmotivated:
            results["transition_motivated"] = _rule("fail", "plan.transitions", f"no transition declared into shots: {unmotivated}")
        elif bad:
            results["transition_motivated"] = _rule("fail", "transition.reason", f"transition without a reason: {bad}")
        else:
            results["transition_motivated"] = _rule("pass", "plan.transitions", "every shot boundary has a motivated transition")

    # R7: vision before code.
    vision = plan.get("vision")
    if vision is None:
        results["vision_before_code"] = _rule("pending", "plan.vision", "no vision block declared")
    elif not isinstance(vision, dict):
        raise CapabilityError("animation.guide_check: plan.vision must be an object")
    elif not isinstance(vision.get("description"), str) or not vision["description"].strip():
        results["vision_before_code"] = _rule("fail", "vision.description", "vision block without a description")
    elif vision.get("vision_first") is False or vision.get("code_before_vision") is True:
        results["vision_before_code"] = _rule("fail", "vision.vision_first", "code was produced before vision")
    else:
        results["vision_before_code"] = _rule("pass", "plan.vision", "vision block present and marked first")

    statuses = [results[rule_id]["status"] for rule_id, _ in GUIDE_RULES]
    if "fail" in statuses:
        verdict = "fail"
    elif "pending" in statuses:
        verdict = "pending"
    else:
        verdict = "pass"
    return {
        "verdict": verdict,
        "rules": [
            {"id": rule_id, "title": title, **results[rule_id]}
            for rule_id, title in GUIDE_RULES
        ],
    }


# ---------------------------------------------------------------------------
# 2. Pure-function time/camera model
# ---------------------------------------------------------------------------

def _easing(name: str, t: float) -> float:
    if name == "linear":
        return t
    if name == "ease_in":
        return t * t
    if name == "ease_out":
        return 1.0 - (1.0 - t) * (1.0 - t)
    if name == "ease_in_out":
        return t * t * (3.0 - 2.0 * t)
    if name == "ease_in_out_cubic":
        return 4.0 * t * t * t if t < 0.5 else 1.0 - pow(-2.0 * t + 2.0, 3) / 2.0
    raise CapabilityError(f"animation.time_camera: unknown easing {name!r} (want linear|ease_in|ease_out|ease_in_out|ease_in_out_cubic)")


def _lerp(a: float, b: float, p: float) -> float:
    return a + (b - a) * p


def _point(spec: dict[str, Any], key: str, default: dict[str, float]) -> dict[str, float]:
    raw = spec.get(key)
    if raw is None:
        return dict(default)
    if not isinstance(raw, dict):
        raise CapabilityError(f"animation.time_camera: {key} must be an object")
    out: dict[str, float] = {}
    for axis, fallback in default.items():
        value = raw.get(axis, fallback)
        if not _is_num(value):
            raise CapabilityError(f"animation.time_camera: {key}.{axis} must be a number")
        out[axis] = float(value)
    return out


def sample_state(t: float, spec: dict[str, Any]) -> dict[str, Any]:
    """Deterministic character/camera state at time ``t`` (seconds).

    ``spec``: {duration_sec, easing, camera:{from:{x,y,zoom}, to:{...}},
    character:{from:{x,y,scale}, to:{...}}, boil:{seed, amplitude_px, fps}}.
    ``t`` outside [0, duration_sec] is an error, not a clamp: clamping
    would silently invent a state the caller did not ask for.
    """
    spec = _require_dict(spec, "spec")
    if not _is_num(t):
        raise CapabilityError("animation.time_camera: t must be a number")
    duration = spec.get("duration_sec")
    if not _is_num(duration) or float(duration) <= 0:
        raise CapabilityError("animation.time_camera: spec.duration_sec must be > 0")
    duration = float(duration)
    t = float(t)
    if t < 0.0 or t > duration:
        raise CapabilityError(f"animation.time_camera: t={t} outside [0, {duration}]")
    progress = t / duration
    eased = _easing(str(spec.get("easing", "ease_in_out")), progress)

    camera_spec = spec.get("camera") or {}
    if not isinstance(camera_spec, dict):
        raise CapabilityError("animation.time_camera: spec.camera must be an object")
    cam_from = _point(camera_spec, "from", {"x": 0.0, "y": 0.0, "zoom": 1.0})
    cam_to = _point(camera_spec, "to", {"x": 0.0, "y": 0.0, "zoom": 1.0})
    camera = {k: _lerp(cam_from[k], cam_to[k], eased) for k in ("x", "y", "zoom")}

    char_spec = spec.get("character") or {}
    if not isinstance(char_spec, dict):
        raise CapabilityError("animation.time_camera: spec.character must be an object")
    ch_from = _point(char_spec, "from", {"x": 0.5, "y": 0.5, "scale": 1.0})
    ch_to = _point(char_spec, "to", {"x": 0.5, "y": 0.5, "scale": 1.0})
    character = {k: _lerp(ch_from[k], ch_to[k], eased) for k in ("x", "y", "scale")}

    boil_spec = spec.get("boil") or {}
    if not isinstance(boil_spec, dict):
        raise CapabilityError("animation.time_camera: spec.boil must be an object")
    seed = boil_spec.get("seed", 0)
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise CapabilityError("animation.time_camera: spec.boil.seed must be an integer")
    amplitude = boil_spec.get("amplitude_px", 1.5)
    if not _is_num(amplitude) or float(amplitude) < 0:
        raise CapabilityError("animation.time_camera: spec.boil.amplitude_px must be >= 0")
    fps = boil_spec.get("fps", 12)
    if not _is_num(fps) or float(fps) <= 0:
        raise CapabilityError("animation.time_camera: spec.boil.fps must be > 0")
    frame = int(math.floor(t * float(fps)))
    rng = random.Random(seed * 1000003 + frame * 9176 + 13)
    boil = {
        "frame": frame,
        "jitter_x_px": rng.uniform(-float(amplitude), float(amplitude)),
        "jitter_y_px": rng.uniform(-float(amplitude), float(amplitude)),
    }
    return {
        "t": t,
        "duration_sec": duration,
        "progress": progress,
        "eased_progress": eased,
        "easing": str(spec.get("easing", "ease_in_out")),
        "camera": camera,
        "character": character,
        "boil": boil,
    }


# ---------------------------------------------------------------------------
# 3. Shots/loops timeline structure
# ---------------------------------------------------------------------------

def validate_timeline(plan: dict[str, Any]) -> dict[str, Any]:
    """Validate a shot plan: continuous, no overlap, no undeclared gap.

    ``plan``: {shots: [{shot_id, start_sec, end_sec, duration_sec?,
    loop_count?, transition?}], gaps?: [{start_sec, end_sec, reason}]}.
    A gap between shots is only legal when a gap entry covers exactly
    that interval with a non-empty reason (explicitly declared hold).
    Returns the normalised plan (shots sorted by start).
    """
    plan = _require_dict(plan, "plan")
    shots = plan.get("shots")
    if not isinstance(shots, list) or not shots:
        raise CapabilityError("animation.timeline: plan.shots must be a non-empty list")
    normalised: list[dict[str, Any]] = []
    seen: set[str] = set()
    for shot in shots:
        if not isinstance(shot, dict):
            raise CapabilityError("animation.timeline: each shot must be an object")
        sid = shot.get("shot_id")
        if not isinstance(sid, str) or not sid.strip():
            raise CapabilityError("animation.timeline: each shot requires a non-empty shot_id")
        sid = sid.strip()
        if sid in seen:
            raise CapabilityError(f"animation.timeline: duplicate shot_id {sid!r}")
        seen.add(sid)
        if not _is_num(shot.get("start_sec")) or not _is_num(shot.get("end_sec")):
            raise CapabilityError(f"animation.timeline: shot {sid!r} requires numeric start_sec/end_sec")
        start, end = float(shot["start_sec"]), float(shot["end_sec"])
        if end <= start:
            raise CapabilityError(f"animation.timeline: shot {sid!r} requires end_sec > start_sec")
        if shot.get("duration_sec") is not None:
            if not _is_num(shot["duration_sec"]) or abs(float(shot["duration_sec"]) - (end - start)) > _EPS:
                raise CapabilityError(f"animation.timeline: shot {sid!r} duration_sec != end_sec - start_sec")
        loop_count = shot.get("loop_count", shot.get("loops"))
        if isinstance(loop_count, dict):
            loop_count = loop_count.get("count")
        if loop_count is not None:
            if not isinstance(loop_count, int) or isinstance(loop_count, bool) or loop_count < 1:
                raise CapabilityError(f"animation.timeline: shot {sid!r} loop_count must be an integer >= 1")
        transition = shot.get("transition")
        if transition is not None:
            if not isinstance(transition, dict) or not transition.get("type"):
                raise CapabilityError(f"animation.timeline: shot {sid!r} transition requires a type")
            if transition.get("duration_sec") is not None:
                if not _is_num(transition["duration_sec"]) or not (0 < float(transition["duration_sec"]) <= end - start):
                    raise CapabilityError(f"animation.timeline: shot {sid!r} transition duration_sec must be within the shot")
        entry = dict(shot)
        entry["shot_id"] = sid
        entry["start_sec"] = start
        entry["end_sec"] = end
        entry["duration_sec"] = end - start
        normalised.append(entry)
    normalised.sort(key=lambda s: s["start_sec"])

    gaps = plan.get("gaps") or []
    if not isinstance(gaps, list):
        raise CapabilityError("animation.timeline: plan.gaps must be a list")
    gap_intervals: list[tuple[float, float]] = []
    for gap in gaps:
        if not isinstance(gap, dict) or not _is_num(gap.get("start_sec")) or not _is_num(gap.get("end_sec")):
            raise CapabilityError("animation.timeline: each gap requires numeric start_sec/end_sec")
        if float(gap["end_sec"]) <= float(gap["start_sec"]):
            raise CapabilityError("animation.timeline: each gap requires end_sec > start_sec")
        if not isinstance(gap.get("reason"), str) or not gap["reason"].strip():
            raise CapabilityError("animation.timeline: each gap requires a non-empty reason")
        gap_intervals.append((float(gap["start_sec"]), float(gap["end_sec"])))

    if abs(normalised[0]["start_sec"] - 0.0) > _EPS:
        if (0.0, normalised[0]["start_sec"]) not in gap_intervals:
            raise CapabilityError("animation.timeline: timeline must start at 0.0 or declare a leading gap")
    for prev, nxt in zip(normalised, normalised[1:]):
        if nxt["start_sec"] < prev["end_sec"] - _EPS:
            raise CapabilityError(
                f"animation.timeline: overlap between {prev['shot_id']!r} and {nxt['shot_id']!r}"
            )
        if nxt["start_sec"] > prev["end_sec"] + _EPS:
            if (prev["end_sec"], nxt["start_sec"]) not in gap_intervals:
                raise CapabilityError(
                    f"animation.timeline: gap {prev['end_sec']}..{nxt['start_sec']} between "
                    f"{prev['shot_id']!r} and {nxt['shot_id']!r} is not declared in plan.gaps"
                )
    return {
        "shots": normalised,
        "gaps": gaps,
        "shot_count": len(normalised),
        "total_duration_sec": normalised[-1]["end_sec"],
        "continuous": True,
    }


# ---------------------------------------------------------------------------
# 4. Brush-wipe transition specification
# ---------------------------------------------------------------------------

def validate_brush_wipe(spec: dict[str, Any]) -> dict[str, Any]:
    """Validate a brush-wipe spec and return its executable render plan.

    ``spec``: {direction, duration_sec, brush:{stroke_width_px,
    roughness (0..1), seed}, from_shot?, to_shot?, reason?}.  The plan
    describes wipe phases and coverage; it renders no video itself.
    """
    spec = _require_dict(spec, "spec")
    direction = spec.get("direction")
    if direction not in BRUSH_WIPE_DIRECTIONS:
        raise CapabilityError(
            f"animation.brush_wipe: direction must be one of {list(BRUSH_WIPE_DIRECTIONS)}, got {direction!r}"
        )
    duration = spec.get("duration_sec")
    if not _is_num(duration) or not (0.2 <= float(duration) <= 3.0):
        raise CapabilityError("animation.brush_wipe: duration_sec must be within [0.2, 3.0]")
    brush = spec.get("brush") or {}
    if not isinstance(brush, dict):
        raise CapabilityError("animation.brush_wipe: brush must be an object")
    width = brush.get("stroke_width_px", 24)
    if not _is_num(width) or float(width) <= 0:
        raise CapabilityError("animation.brush_wipe: brush.stroke_width_px must be > 0")
    roughness = brush.get("roughness", 0.5)
    if not _is_num(roughness) or not (0.0 <= float(roughness) <= 1.0):
        raise CapabilityError("animation.brush_wipe: brush.roughness must be within [0, 1]")
    seed = brush.get("seed", 0)
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise CapabilityError("animation.brush_wipe: brush.seed must be an integer")
    duration = float(duration)
    return {
        "type": "brush_wipe",
        "direction": direction,
        "duration_sec": duration,
        "brush": {
            "stroke_width_px": float(width),
            "roughness": float(roughness),
            "seed": seed,
            "texture": brush.get("texture", "dry_brush"),
        },
        "from_shot": spec.get("from_shot"),
        "to_shot": spec.get("to_shot"),
        "reason": spec.get("reason"),
        "phases": [
            {"at_progress": 0.0, "coverage": 0.0, "note": "wipe edge enters"},
            {"at_progress": 0.5, "coverage": 0.5, "note": "half the frame wiped"},
            {"at_progress": 1.0, "coverage": 1.0, "note": "wipe complete, new shot fully revealed"},
        ],
        "render_steps": [
            "render from_shot frame at wipe start",
            f"paint brush edge travelling {direction} over {duration} s",
            "render to_shot frame at wipe end",
        ],
    }


# ---------------------------------------------------------------------------
# 5. Render self-check plan (contact sheet / strip / crop-at)
# ---------------------------------------------------------------------------

def _frame_files(frames_dir: Path) -> list[Path]:
    if not frames_dir.is_dir():
        raise CapabilityError(f"animation.render_check: frames_dir {frames_dir} is not a directory")
    files = sorted(p for p in frames_dir.iterdir() if p.is_file() and p.suffix.lower() in _IMAGE_EXTS)
    if not files:
        raise CapabilityError(f"animation.render_check: no image frames found in {frames_dir}")
    return files


def build_render_check(
    shots: list[dict[str, Any]],
    frames_dir: str | None = None,
    strip_step_sec: float = 0.5,
    crop_at: dict[str, Any] | None = None,
    cell: tuple[int, int] = (320, 180),
) -> dict[str, Any]:
    """Build the render self-check plan; build a contact sheet if frames exist.

    Without ``frames_dir`` the result is a plan only (frame indices are
    null, no PNG is written).  With frames, the contact sheet is a real
    PIL grid: rows = shots, columns = first / mid / last frame of the
    shot.  Frame index for a time is the proportional index over the
    whole timeline (frame count is the only frame metadata assumed).
    """
    if not isinstance(shots, list) or not shots:
        raise CapabilityError("animation.render_check: shots must be a non-empty list")
    if not _is_num(strip_step_sec) or float(strip_step_sec) <= 0:
        raise CapabilityError("animation.render_check: strip_step_sec must be > 0")
    parsed: list[dict[str, Any]] = []
    for shot in shots:
        if not isinstance(shot, dict) or not _is_num(shot.get("start_sec")) or not _is_num(shot.get("end_sec")):
            raise CapabilityError("animation.render_check: each shot requires numeric start_sec/end_sec")
        start, end = float(shot["start_sec"]), float(shot["end_sec"])
        if end <= start:
            raise CapabilityError("animation.render_check: each shot requires end_sec > start_sec")
        parsed.append({"shot_id": str(shot.get("shot_id") or "?"), "start_sec": start, "end_sec": end})
    parsed.sort(key=lambda s: s["start_sec"])
    total = parsed[-1]["end_sec"]

    files: list[Path] | None = None
    if frames_dir is not None:
        files = _frame_files(Path(frames_dir))

    def frame_index(t: float) -> int | None:
        if files is None:
            return None
        return min(len(files) - 1, max(0, int(math.floor(t / total * len(files)))))

    contact: list[dict[str, Any]] = []
    for shot in parsed:
        start, end = shot["start_sec"], shot["end_sec"]
        mid = (start + end) / 2.0
        last = end - min(0.04, (end - start) / 4.0)
        contact.append({
            "shot_id": shot["shot_id"],
            "first": {"time_sec": start, "frame_index": frame_index(start)},
            "mid": {"time_sec": mid, "frame_index": frame_index(mid)},
            "last": {"time_sec": last, "frame_index": frame_index(last)},
        })

    strip: list[dict[str, Any]] = []
    t = 0.0
    while t < total:
        strip.append({"time_sec": round(t, 4), "frame_index": frame_index(t)})
        t += float(strip_step_sec)
    if not strip or strip[-1]["time_sec"] < total:
        strip.append({"time_sec": total, "frame_index": frame_index(total - 1e-9)})

    crop_plan: dict[str, Any] | None = None
    if crop_at is not None:
        if not isinstance(crop_at, dict) or not _is_num(crop_at.get("x")) or not _is_num(crop_at.get("y")):
            raise CapabilityError("animation.render_check: crop_at requires numeric x/y in [0, 1]")
        x, y = float(crop_at["x"]), float(crop_at["y"])
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise CapabilityError("animation.render_check: crop_at x/y must be within [0, 1]")
        size = crop_at.get("size_px", 320)
        if not _is_num(size) or float(size) <= 0:
            raise CapabilityError("animation.render_check: crop_at size_px must be > 0")
        crop_plan = {
            "world_point": {"x": x, "y": y},
            "size_px": float(size),
            "label": crop_at.get("label", "world_point"),
            "per_shot_mid": [
                {"shot_id": s["shot_id"], "time_sec": (s["start_sec"] + s["end_sec"]) / 2.0,
                 "frame_index": frame_index((s["start_sec"] + s["end_sec"]) / 2.0)}
                for s in parsed
            ],
        }

    plan: dict[str, Any] = {
        "shots": parsed,
        "total_duration_sec": total,
        "contact_sheet": contact,
        "strip": strip,
        "crop_at": crop_plan,
        "frame_count": len(files) if files is not None else None,
        "frames_dir": frames_dir,
        "has_frames": files is not None,
    }
    return plan, files


def _build_contact_sheet_png(plan: dict[str, Any], files: list[Path], out_path: Path) -> dict[str, Any]:
    from PIL import Image, ImageDraw

    cell_w, cell_h = 320, 180
    cols = 3
    rows = len(plan["shots"])
    sheet = Image.new("RGB", (cols * cell_w, rows * (cell_h + 18)), "white")
    draw = ImageDraw.Draw(sheet)
    for r, pick in enumerate(plan["contact_sheet"]):
        for c, key in enumerate(("first", "mid", "last")):
            idx = pick[key]["frame_index"]
            if idx is None:
                raise CapabilityError("animation.render_check: contact sheet requires frame indices")
            img = Image.open(files[idx]).convert("RGB")
            img.thumbnail((cell_w, cell_h))
            x0 = c * cell_w + (cell_w - img.width) // 2
            y0 = r * (cell_h + 18) + (cell_h - img.height) // 2
            sheet.paste(img, (x0, y0))
            draw.text((c * cell_w + 4, r * (cell_h + 18) + cell_h + 2),
                      f"{pick['shot_id']}:{key}", fill="black")
    sheet.save(out_path)
    return {"contact_sheet_png": str(out_path), "sheet_size": list(sheet.size)}


# ---------------------------------------------------------------------------
# 6. tuantuan 11-second demo spec
# ---------------------------------------------------------------------------

def build_demo_spec(seed: int = 7) -> dict[str, Any]:
    """An 11-second, 3-shot demo plan for hevi's own tuantuan.

    Shot emotions move happy -> thinking -> surprised, views move
    front -> three_quarter -> front, and both brush-wipe transitions
    are motivated.  Every view/emotion is validated against the
    expression_rig enums; the brush template is validated against the
    brushpaint template list when that engine is importable.
    """
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise CapabilityError("animation.tuantuan_demo: seed must be an integer")
    views, emotions = _expression_enums()
    shot_defs = [
        ("s1", 0.0, 4.0, "front", "happy", "tuantuan waves hello to the viewer",
         ["character_wave", "camera_slow_push_in"]),
        ("s2", 4.0, 7.5, "three_quarter", "thinking", "tuantuan pauses, looks aside, thinks",
         ["character_head_tilt", "camera_hold"]),
        ("s3", 7.5, 11.0, "front", "surprised", "tuantuan turns back, eyes wide at a surprise",
         ["character_turn", "camera_push_in"]),
    ]
    for sid, start, end, view, emotion, _event, _motion in shot_defs:
        if view not in views:
            raise CapabilityError(f"animation.tuantuan_demo: unknown view {view!r} (from expression_rig)")
        if emotion not in emotions:
            raise CapabilityError(f"animation.tuantuan_demo: unknown emotion {emotion!r} (from expression_rig)")
    templates = _brush_templates()
    template = "pond_night"
    if templates is not None and template not in templates:
        raise CapabilityError(f"animation.tuantuan_demo: brush template {template!r} not in brushpaint templates {templates}")
    shots: list[dict[str, Any]] = []
    for i, (sid, start, end, view, emotion, event, motion) in enumerate(shot_defs):
        shot: dict[str, Any] = {
            "shot_id": sid,
            "start_sec": start,
            "end_sec": end,
            "duration_sec": end - start,
            "character": "tuantuan",
            "view": view,
            "emotion": emotion,
            "event": event,
            "motion": motion,
            "has_text": False,
            "text_elements": [],
            "medium": "handpaint_brush",
            "brush_style": {"template": template, "seed": seed},
        }
        if i > 0:
            shot["transition"] = {
                "type": "brush_wipe",
                "direction": "left_to_right" if i == 1 else "top_to_bottom",
                "duration_sec": 0.6,
            }
        shots.append(shot)
    plan: dict[str, Any] = {
        "title": "tuantuan 11s hand-painted demo",
        "character": "tuantuan",
        "medium": "handpaint_brush",
        "total_duration_sec": 11.0,
        "vision": {
            "description": "tuantuan greets, thinks, then reacts with surprise, in one hand-painted brush style",
            "reference": "expression_rig model sheet for tuantuan + brushpaint pond_night template",
            "vision_first": True,
        },
        "shots": shots,
        "transitions": [
            {"from_shot": "s1", "to_shot": "s2", "type": "brush_wipe",
             "direction": "left_to_right", "duration_sec": 0.6,
             "reason": "wipe follows tuantuan turning aside to think"},
            {"from_shot": "s2", "to_shot": "s3", "type": "brush_wipe",
             "direction": "top_to_bottom", "duration_sec": 0.6,
             "reason": "wipe drops in as the surprise lands"},
        ],
    }
    return plan


# ---------------------------------------------------------------------------
# Capability render wrappers
# ---------------------------------------------------------------------------

def _render_guide_check(params, out_dir, *, duration, aspect, seed):
    plan = _require_dict(params.get("plan"), "plan")
    result = check_guide(plan)
    report = _write_json(Path(out_dir), "guide_check.json", result)
    return _result_for_report(report, result)


def _render_time_camera(params, out_dir, *, duration, aspect, seed):
    spec = _require_dict(params.get("spec"), "spec")
    times = params.get("times")
    if times is None:
        if params.get("t") is None:
            raise CapabilityError("animation.time_camera: provide t or times")
        times = [params["t"]]
    if not isinstance(times, list) or not times:
        raise CapabilityError("animation.time_camera: times must be a non-empty list")
    states = [sample_state(t, spec) for t in times]
    payload = {"states": states}
    report = _write_json(Path(out_dir), "time_camera.json", payload)
    return _result_for_report(report, payload)


def _render_timeline(params, out_dir, *, duration, aspect, seed):
    plan = _require_dict(params.get("plan"), "plan")
    normalised = validate_timeline(plan)
    report = _write_json(Path(out_dir), "timeline.json", normalised)
    return _result_for_report(report, normalised)


def _render_brush_wipe(params, out_dir, *, duration, aspect, seed):
    spec = _require_dict(params.get("spec"), "spec")
    plan = validate_brush_wipe(spec)
    report = _write_json(Path(out_dir), "brush_wipe_plan.json", plan)
    return _result_for_report(report, plan)


def _render_render_check(params, out_dir, *, duration, aspect, seed):
    shots = params.get("shots")
    if not isinstance(shots, list):
        raise CapabilityError("animation.render_check: shots must be a list")
    plan, files = build_render_check(
        shots,
        frames_dir=params.get("frames_dir"),
        strip_step_sec=float(params.get("strip_step_sec", 0.5)),
        crop_at=params.get("crop_at"),
    )
    out_dir = Path(out_dir)
    extra: dict[str, Any] = {}
    png_path: str | None = None
    if files is not None:
        png_file = out_dir / "contact_sheet.png"
        out_dir.mkdir(parents=True, exist_ok=True)
        extra = _build_contact_sheet_png(plan, files, png_file)
        png_path = str(png_file)
    report = _write_json(out_dir, "render_check.json", plan)
    result = _result_for_report(report, plan, extra_qa=extra)
    if png_path is not None:
        result.png = png_path
        result.sha256 = compute_sha256(Path(png_path))
    return result


def _render_demo(params, out_dir, *, duration, aspect, seed):
    plan = build_demo_spec(seed=int(params.get("seed", seed or 7)))
    guide = check_guide(plan)
    timeline = validate_timeline(plan)
    if guide["verdict"] != "pass":
        raise CapabilityError(f"animation.tuantuan_demo: demo plan failed its own guide check: {guide}")
    payload = {"plan": plan, "guide_check": guide, "timeline": timeline}
    report = _write_json(Path(out_dir), "tuantuan_demo.json", payload)
    return _result_for_report(report, payload, extra_qa={
        "total_duration_sec": 11.0, "shot_count": 3, "guide_verdict": "pass",
    })


def register_handpaint_anim_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    specs = [
        ("animation.guide_check", "line", _render_guide_check,
         {"type": "object", "properties": {"plan": {"type": "object"}}, "required": ["plan"], "additionalProperties": False},
         "Guide-rule check: validates an animation plan against the seven deterministic animation-guide rules; missing evidence is pending, never a pass."),
        ("animation.time_camera", "line", _render_time_camera,
         {"type": "object", "properties": {"spec": {"type": "object"}, "t": {"type": "number"}, "times": {"type": "array", "items": {"type": "number"}}}, "additionalProperties": False},
         "Pure-function time/camera model: deterministic character/camera state at given time(s), with easing and seeded boiling-linework jitter."),
        ("animation.timeline", "line", _render_timeline,
         {"type": "object", "properties": {"plan": {"type": "object"}}, "required": ["plan"], "additionalProperties": False},
         "Shots/loops timeline: validates shot continuity (no overlap, no undeclared gap), loop counts, and transition durations."),
        ("animation.brush_wipe", "line", _render_brush_wipe,
         {"type": "object", "properties": {"spec": {"type": "object"}}, "required": ["spec"], "additionalProperties": False},
         "Brush-wipe transition spec: validates direction, duration, and brush parameters and emits an executable render plan."),
        ("animation.render_check", "line", _render_render_check,
         {"type": "object", "properties": {"shots": {"type": "array"}, "frames_dir": {"type": "string"}, "strip_step_sec": {"type": "number"}, "crop_at": {"type": "object"}}, "required": ["shots"], "additionalProperties": False},
         "Render self-check plan: per-shot first/mid/last contact-sheet picks, frame strip, and crop-at plan; builds a real PIL contact sheet only when real frames are supplied."),
        ("animation.tuantuan_demo", "line", _render_demo,
         {"type": "object", "properties": {"seed": {"type": "integer"}}, "additionalProperties": False},
         "11-second tuantuan demo plan: 3 shots, brush-wipe transitions, happy->thinking->surprised, with a passing guide check and timeline validation."),
    ]
    names: list[str] = []
    for name, kind, render, schema, description in specs:
        register(Capability(
            name=name, kind=kind, aspects=["16:9", "9:16", "1:1"],
            params_schema=schema, cpu_cost_hint=0.0, render=render,
            has_media_output=False, description=description, line="handpaint",
        ))
        names.append(name)
    return names


register_handpaint_anim_capabilities_once()
