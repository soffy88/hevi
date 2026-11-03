"""Single GSAP timeline plan with frame对照 (``animation.gsap_timeline_plan``).

Clean-room method intake, written from the method description only.
It fills the gap left by ``image.vector_path``: vector_path reports
geometry numbers for a shape, but says nothing about motion over
time. This module owns motion over time -- exactly one timeline,
tweens on it, a frame-addressable sample table, and comparison
points against a source film.

Method:
* One timeline only. There is no second timeline to drift against;
  every tween belongs to the single timeline and is sorted by
  start time in the output.
* A tween animates one numeric property of one target over one
  window. Two tweens on the same target and property may not
  overlap; an overlap raises instead of letting the later tween
  silently win.
* Every frame is addressable: frame ids are f0000, f0001, ... and
  each frame row carries the interpolated value of every property
  that has started, holding its last value after its tween ends.
  Easing names come from a closed catalogue and are evaluated
  (linear, sine in-out, power1/power2 out), not just recorded.
* Source对照 points are caller-supplied (time plus state). For
  each one the plan reports the planned value at the nearest frame
  and the numeric delta per property, so a human can see exactly
  where the plan departs from the source.

Scope, stated honestly: this is a plan only. It emits no video,
no rendered frames and no GSAP runtime code to execute -- the
timeline description is what a renderer consumes. Frame tables
are capped at 10,000 frames; larger plans raise rather than
emitting a huge table.

Failure contract: a non-positive duration, a tween outside the
timeline or with end<=start, a non-numeric tween value, an unknown
easing, overlapping tweens on one target/property, a source point
outside the timeline, or a frame table over the cap all raise
CapabilityError.
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
_MAX_FRAMES = 10000
_EASES = ("none", "linear", "sine.inOut", "power1.out", "power2.out")


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_num(value: Any, what: str) -> float:
    if not _is_num(value):
        raise CapabilityError(f"animation.gsap_timeline_plan: {what} must be a number")
    return float(value)


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(f"animation.gsap_timeline_plan: {what} must be a non-empty string")
    return value.strip()


def _ease(name: str, t: float) -> float:
    if name in ("none", "linear"):
        return t
    if name == "sine.inOut":
        return 0.5 - 0.5 * math.cos(math.pi * t)
    if name == "power1.out":
        return 1.0 - (1.0 - t) ** 2
    if name == "power2.out":
        return 1.0 - (1.0 - t) ** 3
    raise CapabilityError(f"animation.gsap_timeline_plan: unknown ease {name!r}")


def build_gsap_timeline(plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise CapabilityError("animation.gsap_timeline_plan: plan must be a JSON object")
    duration = _require_num(plan.get("duration_sec"), "duration_sec")
    if duration <= 0:
        raise CapabilityError("animation.gsap_timeline_plan: duration_sec must be > 0")
    fps = plan.get("fps", 30)
    if not isinstance(fps, int) or isinstance(fps, bool) or fps < 1 or fps > 120:
        raise CapabilityError("animation.gsap_timeline_plan: fps must be an integer between 1 and 120")
    frame_count = int(math.floor(duration * fps)) + 1
    if frame_count > _MAX_FRAMES:
        raise CapabilityError("animation.gsap_timeline_plan: frame table would exceed 10000 frames")
    tweens_raw = plan.get("tweens")
    if not isinstance(tweens_raw, list) or not tweens_raw:
        raise CapabilityError("animation.gsap_timeline_plan: tweens must be a non-empty list")
    tweens: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for i, tw in enumerate(tweens_raw):
        if not isinstance(tw, dict):
            raise CapabilityError(f"animation.gsap_timeline_plan: tween {i} must be a JSON object")
        tid = _require_str(tw.get("id"), f"tween {i}.id")
        if tid in seen_ids:
            raise CapabilityError(f"animation.gsap_timeline_plan: duplicate tween id {tid!r}")
        seen_ids.add(tid)
        target = _require_str(tw.get("target"), f"tween {i}.target")
        prop = _require_str(tw.get("property"), f"tween {i}.property")
        start = _require_num(tw.get("start_sec"), f"tween {i}.start_sec")
        end = _require_num(tw.get("end_sec"), f"tween {i}.end_sec")
        if start < 0 or end > duration + _TOL or end <= start:
            raise CapabilityError(f"animation.gsap_timeline_plan: tween {tid!r} must lie inside the timeline with end > start")
        ease = tw.get("ease", "none")
        if ease not in _EASES:
            raise CapabilityError(f"animation.gsap_timeline_plan: tween {tid!r} unknown ease {ease!r}")
        tweens.append({
            "id": tid, "target": target, "property": prop,
            "from_value": _require_num(tw.get("from_value"), f"tween {i}.from_value"),
            "to_value": _require_num(tw.get("to_value"), f"tween {i}.to_value"),
            "start_sec": start, "end_sec": end, "ease": ease,
        })
    for a in range(len(tweens)):
        for b in range(a + 1, len(tweens)):
            x, y = tweens[a], tweens[b]
            if x["target"] == y["target"] and x["property"] == y["property"]:
                if x["start_sec"] < y["end_sec"] - _TOL and y["start_sec"] < x["end_sec"] - _TOL:
                    raise CapabilityError(
                        f"animation.gsap_timeline_plan: tweens {x['id']!r} and {y['id']!r} overlap on {x['target']}.{x['property']}"
                    )
    tweens.sort(key=lambda t: (t["start_sec"], t["id"]))

    def value_at(tw: dict[str, Any], t: float) -> float | None:
        if t < tw["start_sec"] - _TOL:
            return None
        if t >= tw["end_sec"]:
            return tw["to_value"]
        p = (t - tw["start_sec"]) / (tw["end_sec"] - tw["start_sec"])
        return tw["from_value"] + (tw["to_value"] - tw["from_value"]) * _ease(tw["ease"], p)

    frame_table: list[dict[str, Any]] = []
    for fi in range(frame_count):
        t = fi / fps
        values: dict[str, float] = {}
        for tw in tweens:
            v = value_at(tw, t)
            if v is not None:
                values[f"{tw['target']}.{tw['property']}"] = round(v, 6)
        frame_table.append({"frame_id": f"f{fi:04d}", "frame_index": fi, "time_sec": round(t, 3), "values": values})

    comparisons: list[dict[str, Any]] = []
    for i, sp in enumerate(plan.get("source_points", [])):
        if not isinstance(sp, dict):
            raise CapabilityError(f"animation.gsap_timeline_plan: source point {i} must be a JSON object")
        at = _require_num(sp.get("at_sec"), f"source point {i}.at_sec")
        if at < 0 or at > duration + _TOL:
            raise CapabilityError(f"animation.gsap_timeline_plan: source point {i} lies outside the timeline")
        state = sp.get("state")
        if not isinstance(state, dict) or not state:
            raise CapabilityError(f"animation.gsap_timeline_plan: source point {i}.state must be a non-empty object")
        fi = min(frame_count - 1, int(round(at * fps)))
        planned = frame_table[fi]["values"]
        deltas: dict[str, Any] = {}
        for key, src_val in state.items():
            if not _is_num(src_val):
                raise CapabilityError(f"animation.gsap_timeline_plan: source point {i} state values must be numbers")
            if key in planned:
                deltas[key] = {"source_value": float(src_val), "planned_value": planned[key], "delta": round(planned[key] - float(src_val), 6)}
            else:
                deltas[key] = {"source_value": float(src_val), "planned_value": None, "delta": None}
        comparisons.append({
            "id": _require_str(sp.get("id"), f"source point {i}.id"),
            "at_sec": at,
            "nearest_frame_id": frame_table[fi]["frame_id"],
            "nearest_frame_index": fi,
            "deltas": deltas,
        })

    return {
        "capability": "animation.gsap_timeline_plan",
        "timeline_id": plan.get("timeline_id", "timeline_1"),
        "timeline_count": 1,
        "duration_sec": duration,
        "fps": fps,
        "frame_count": frame_count,
        "tweens": tweens,
        "ease_catalog": list(_EASES),
        "frame_table": frame_table,
        "source_comparisons": comparisons,
        "media": "plan_only_no_video",
        "media_note": "No video is rendered; the frame table is the addressable plan a renderer consumes.",
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    result = build_gsap_timeline(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "gsap_timeline_plan.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), "frame_count": result["frame_count"], "tween_count": len(result["tweens"])},
    )


def register_gsap_timeline_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="animation.gsap_timeline_plan",
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
            "Single GSAP timeline plan (clean-room): one timeline, non-overlapping "
            "tweens with evaluated easing, a frame-addressable sample table, and "
            "numeric comparison points against a source film. Plan only, no video."
        ),
        line="animation",
    ))
    return ["animation.gsap_timeline_plan"]


register_gsap_timeline_capabilities_once()
