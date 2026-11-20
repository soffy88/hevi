"""Motion layout and gesture gate (``qa.motion_layout_gesture_gate``).

Clean-room restatement of the motiondivision/motion method
(see ``ANIMATION_STUDIO_18_ATTRIBUTION.md``); no upstream
code appears here. Motion's increment over hevi's GSAP
timeline and Anime.js vocabulary is layout animation and
gesture animation: an element moves because its layout
changed, or because a gesture started and ended. Plain
tweening is already covered by GSAP/Anime.js and is out of
scope here, so a transition whose kind is tween fails this
gate. Every layout transition must declare its before and
after layout; every gesture must declare its start and end
state.
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

LAYOUT_GESTURE_KINDS = ("layout", "gesture")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_motion_layout_gesture(plan: Any) -> dict[str, Any]:
    """Validate a Motion-style layout/gesture plan.

    Verdicts are ``pass`` / ``fail`` only. A plan fails when
    it is not an object, when the transition list is empty,
    when a transition lacks an element or a positive duration,
    when its kind is not layout or gesture (tweening belongs
    to GSAP/Anime.js), when a layout transition does not
    declare its before and after layout, or when a gesture
    does not declare its start and end state.
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
        return fail("plan_not_object", "layout/gesture plan must be a JSON object")
    if "transitions" not in plan:
        return fail("plan_field_missing", "layout/gesture plan must carry 'transitions'")
    transitions = plan["transitions"]
    if not isinstance(transitions, list) or not transitions:
        return fail("transitions_empty", "layout/gesture plan needs at least one transition")
    for transition in transitions:
        if not isinstance(transition, dict):
            return fail("transition_not_object", "each transition must be an object")
        if not isinstance(transition.get("element"), str) or not transition["element"]:
            return fail("transition_element_missing", "each transition needs an element")
        duration = transition.get("duration_s")
        if not isinstance(duration, (int, float)) or duration <= 0:
            return fail(
                "transition_duration_not_positive",
                f"transition on {transition.get('element')!r} needs a positive duration_s",
            )
        kind = transition.get("kind")
        if kind not in LAYOUT_GESTURE_KINDS:
            return fail(
                "kind_out_of_scope",
                f"kind {kind!r} is out of scope here: only layout and "
                "gesture transitions belong to Motion; tweening belongs "
                "to GSAP/Anime.js",
            )
        if kind == "layout":
            for field in ("layout_before", "layout_after"):
                if not isinstance(transition.get(field), dict):
                    return fail(
                        "layout_state_missing",
                        f"layout transition on {transition['element']!r} must "
                        f"declare {field!r} as an object",
                    )
        else:
            for field in ("start_state", "end_state"):
                if not isinstance(transition.get(field), dict):
                    return fail(
                        "gesture_state_missing",
                        f"gesture transition on {transition['element']!r} must "
                        f"declare {field!r} as an object",
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
    report = check_motion_layout_gesture(params.get("plan"))
    report_path = out_dir / "motion_layout_gesture_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_motion_layout_gesture_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.motion_layout_gesture_gate",
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
                "Motion layout/gesture gate: layout transitions declare "
                "before and after layout, gestures declare start and end "
                "state; tweening is out of scope (GSAP/Anime.js own it)."
            ),
        )
    )
    return ["qa.motion_layout_gesture_gate"]


__all__ = [
    "LAYOUT_GESTURE_KINDS",
    "check_motion_layout_gesture",
    "register_motion_layout_gesture_gate_capabilities_once",
]
