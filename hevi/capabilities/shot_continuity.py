"""Shot continuity and slideshow-oracle gate (``qa.shot_continuity_gate``).

Clean-room method intake, written from the method description only.
No upstream code is used; the upstream licence is PolyForm
non-commercial, so nothing is borrowed beyond the method idea
itself (continuity at boundaries, plus an oracle that rejects
slideshow-like films), re-implemented here in original code.

Method:
* Boundary continuity: a shot element that declares
  ``carries_from`` (an element id in the previous shot) must
  actually exist in the previous shot, and must visibly change
  in the next shot -- its motion is moving or morphing, or it
  lists changed attributes. A carried element that sits unchanged
  is a boundary failure, not a continuity pass.
* Dropped elements: a previous-shot element flagged
  ``continues: true`` that never appears in the next shot is a
  major boundary failure.
* Unexplained appearances: a next-shot element with no
  ``carries_from`` and no entering motion is a minor issue --
  something appeared from nowhere.
* Slideshow oracle: a shot counts as static when its camera is
  static and every element in it is static. When at least 80% of
  shots (and at least 2 shots) are static, the film is
  slideshow-like and the oracle fails it outright, whatever the
  boundary verdicts say. A single shot cannot trigger the oracle.

Verdict: fail when the oracle fires or any major boundary issue
exists; needs_fix when only minor issues exist; pass otherwise.
This gate judges structure only -- it never watches footage.

Failure contract: fewer than 1 shot, duplicate shot or element
ids, a non-positive shot duration, an unknown camera or motion
kind, or a carries_from reference to an element that does not
exist in the previous shot all raise CapabilityError.
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
_CAMERAS = ("static", "pan", "tilt", "dolly", "handheld", "zoom")
_MOTIONS = ("static", "moving", "morphing", "entering", "exiting")


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(f"qa.shot_continuity_gate: {what} must be a non-empty string")
    return value.strip()


def _clean_element(el: Any, shot_id: str) -> dict[str, Any]:
    if not isinstance(el, dict):
        raise CapabilityError(f"qa.shot_continuity_gate: shot {shot_id!r} element must be a JSON object")
    eid = _require_str(el.get("element_id"), f"shot {shot_id!r} element.element_id")
    motion = el.get("motion", "static")
    if motion not in _MOTIONS:
        raise CapabilityError(f"qa.shot_continuity_gate: shot {shot_id!r} element {eid!r} unknown motion {motion!r}")
    changed = el.get("changed_attributes", [])
    if not isinstance(changed, list) or not all(isinstance(c, str) for c in changed):
        raise CapabilityError(f"qa.shot_continuity_gate: shot {shot_id!r} element {eid!r} changed_attributes must be a list of strings")
    carries = el.get("carries_from")
    if carries is not None and not isinstance(carries, str):
        raise CapabilityError(f"qa.shot_continuity_gate: shot {shot_id!r} element {eid!r} carries_from must be a string or null")
    continues = el.get("continues", False)
    if not isinstance(continues, bool):
        raise CapabilityError(f"qa.shot_continuity_gate: shot {shot_id!r} element {eid!r} continues must be a boolean")
    return {"element_id": eid, "motion": motion, "changed_attributes": list(changed),
            "carries_from": carries, "continues": continues}


def check_shot_continuity(plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise CapabilityError("qa.shot_continuity_gate: plan must be a JSON object")
    shots_raw = plan.get("shots")
    if not isinstance(shots_raw, list) or not shots_raw:
        raise CapabilityError("qa.shot_continuity_gate: shots must be a non-empty list")
    shots: list[dict[str, Any]] = []
    seen_shots: set[str] = set()
    for i, sh in enumerate(shots_raw):
        if not isinstance(sh, dict):
            raise CapabilityError(f"qa.shot_continuity_gate: shot {i} must be a JSON object")
        sid = _require_str(sh.get("id"), f"shot {i}.id")
        if sid in seen_shots:
            raise CapabilityError(f"qa.shot_continuity_gate: duplicate shot id {sid!r}")
        seen_shots.add(sid)
        dur = sh.get("duration_sec")
        if not _is_num(dur) or dur <= 0:
            raise CapabilityError(f"qa.shot_continuity_gate: shot {sid!r} duration_sec must be > 0")
        camera = sh.get("camera", "static")
        if camera not in _CAMERAS:
            raise CapabilityError(f"qa.shot_continuity_gate: shot {sid!r} unknown camera {camera!r}")
        elements_raw = sh.get("elements", [])
        if not isinstance(elements_raw, list):
            raise CapabilityError(f"qa.shot_continuity_gate: shot {sid!r} elements must be a list")
        elements = [_clean_element(e, sid) for e in elements_raw]
        ids = [e["element_id"] for e in elements]
        if len(set(ids)) != len(ids):
            raise CapabilityError(f"qa.shot_continuity_gate: shot {sid!r} has duplicate element ids")
        shots.append({"id": sid, "duration_sec": float(dur), "camera": camera, "elements": elements})

    boundaries: list[dict[str, Any]] = []
    for k in range(len(shots) - 1):
        prev, cur = shots[k], shots[k + 1]
        prev_ids = {e["element_id"] for e in prev["elements"]}
        prev_by_id = {e["element_id"]: e for e in prev["elements"]}
        issues: list[dict[str, Any]] = []
        for el in cur["elements"]:
            if el["carries_from"] is not None:
                if el["carries_from"] not in prev_ids:
                    raise CapabilityError(
                        f"qa.shot_continuity_gate: shot {cur['id']!r} element {el['element_id']!r} "
                        f"carries_from unknown previous element {el['carries_from']!r}"
                    )
                visibly_changed = el["motion"] in ("moving", "morphing") or bool(el["changed_attributes"])
                if not visibly_changed:
                    issues.append({
                        "severity": "major", "kind": "carried_but_unchanged",
                        "detail": f"Element {el['element_id']!r} carries from {el['carries_from']!r} but shows no visible change.",
                    })
            elif el["motion"] != "entering":
                issues.append({
                    "severity": "minor", "kind": "unexplained_appearance",
                    "detail": f"Element {el['element_id']!r} appears with no carries_from and no entering motion.",
                })
        for el in prev["elements"]:
            if el["continues"] and el["element_id"] not in {e["element_id"] for e in cur["elements"]}:
                # An element that exits on purpose is not dropped.
                issues.append({
                    "severity": "major", "kind": "element_dropped",
                    "detail": f"Element {el['element_id']!r} was flagged continues but is absent in the next shot.",
                })
        boundaries.append({
            "from_shot": prev["id"], "to_shot": cur["id"],
            "verdict": "fail" if any(i["severity"] == "major" for i in issues) else ("needs_fix" if issues else "pass"),
            "issues": issues,
        })

    static_shots = sum(
        1 for s in shots if s["camera"] == "static" and all(e["motion"] == "static" for e in s["elements"])
    )
    static_fraction = static_shots / len(shots)
    slideshow = len(shots) >= 2 and static_fraction >= 0.8
    oracle = {
        "slideshow_detected": slideshow,
        "static_shot_count": static_shots,
        "shot_count": len(shots),
        "static_fraction": round(static_fraction, 3),
        "note": "Single-shot plans cannot trigger the oracle; it needs at least 2 shots."
        if len(shots) < 2 else "Oracle fires at 80% or more static shots.",
    }
    has_major = any(b["verdict"] == "fail" for b in boundaries)
    has_minor = any(b["issues"] for b in boundaries)
    if slideshow or has_major:
        verdict = "fail"
    elif has_minor:
        verdict = "needs_fix"
    else:
        verdict = "pass"
    return {
        "capability": "qa.shot_continuity_gate",
        "shot_count": len(shots),
        "boundaries": boundaries,
        "oracle": oracle,
        "verdict": verdict,
        "verdict_note": "Fail on slideshow-oracle fire or any major boundary issue; otherwise needs_fix on minor issues, pass on clean.",
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    result = check_shot_continuity(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "shot_continuity_gate.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), "verdict": result["verdict"], "shot_count": result["shot_count"]},
    )


def register_shot_continuity_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="qa.shot_continuity_gate",
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
            "Shot continuity gate (clean-room): boundary checks that a carried "
            "element visibly transforms and is not dropped, plus a slideshow "
            "oracle that fails static-shot films. Structure only, no footage watched."
        ),
        line="qa",
    ))
    return ["qa.shot_continuity_gate"]


register_shot_continuity_capabilities_once()
