"""Segment match gate (``qa.segment_match_gate``).

Clean-room rewrite of the *method* in ``hevi-vs-h3-exemplar-prompts.md``
section 4, gap 2: the exemplar's segment 01 hands off to segment 02
with a hand sweeping across the lens, lower-left to upper-right, at
one speed -- and segment 02 must take it up in the same direction,
at the same speed, from the same state. hevi's existing continuity
discipline (``story.prompt_compiler`` gate 4, entry/exit state
dictionaries) says nothing about gesture direction, speed,
occlusion direction, or rotation phase, and it lives inside one
episode. This gate is the cross-segment match: pure plan level, no
generation, no keys, no budget.

Schema. Each segment in ``plan["segments"]`` (in play order) may
carry:

* ``outgoing`` -- what the segment hands off: ``gesture`` (the
  hand-off gesture or occluding object), ``direction`` (the
  direction of travel), ``speed`` (a tier label or a number),
  ``end_state`` (the last-frame state), plus optional
  ``occlusion_direction`` and ``rotation_phase``.
* ``incoming`` -- what the next segment takes up: ``direction``
  (the take-up direction), ``speed``, ``start_state`` (the first-frame
  state), plus optional ``occlusion_direction`` and
  ``rotation_phase`` (and an optional ``gesture`` when the
  incoming side names the gesture it continues).

Boundary rule. For every boundary between consecutive segments,
the earlier segment's ``outgoing`` and the later segment's
``incoming`` must agree on direction, speed, and -- when either
side declares them -- rotation phase and occlusion direction;
the outgoing ``end_state`` must equal the incoming
``start_state``. A boundary whose outgoing or incoming side is
missing, or whose values disagree, fails. The first segment's
``incoming`` and the last segment's ``outgoing`` belong to
boundaries outside this plan and are shape-checked when present
but not cross-checked.

Hand-off kind (gap 7). Each side may declare ``handoff_kind`` from
a closed vocabulary -- ``gesture`` / ``wipe`` / ``element`` /
``rotation`` / ``fabric`` / ``gaze`` -- naming what carries the
match across the cut. When either side declares a kind, the other
must declare the same one. An element/fabric hand-off (gauze,
floor reflection, a hanging veil) must name the element in
``element_name`` on both sides, and the element names must agree.
``direction`` holds direction values only: stuffing an element
name into ``direction`` (``"gauze texture"``, ``"floor
reflection"``, ``"into sleeve"``) fails -- the element belongs in
``element_name`` and the travel belongs in ``direction``. The
``gesture`` field stays free descriptive text; element names are
welcome there.

Single-segment plans cannot prove a match: a lone segment with
no ``outgoing`` / ``incoming`` record is reported ``not_checked``
-- never passed -- and a lone segment that does carry both sides
is likewise ``not_checked``, because no boundary exists to judge
them against. ``not_checked`` here is a real verdict with
``ok`` false, not a pass: callers must not treat it as approval.

The entry/exit state dictionaries of ``story.prompt_compiler``
gate 4 are untouched by this module; this gate adds the match
fields alongside them and never rewrites them.
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

_WS_RE = re.compile(r"\s+")

# Closed hand-off vocabulary (gap 7). ``element`` / ``fabric`` name
# the thing that carries the match (gauze, a reflection); ``gesture``
# / ``wipe`` / ``rotation`` / ``gaze`` name the motion that does.
HANDOFF_KINDS = ("gesture", "wipe", "element", "rotation", "fabric", "gaze")
_ELEMENT_HANDOFF_KINDS = ("element", "fabric")

# Words that name a hand-off element, never a direction. A direction
# value containing one of these fails (gap 7): the element belongs
# in ``element_name``, the travel in ``direction``.
_ELEMENT_TOKENS = (
    "gauze", "fabric", "sleeve", "reflection", "veil", "curtain",
    "texture", "gossamer",
    "纱", "反光", "袖", "帘", "纹理", "织物", "面纱",
)


def _direction_contains_element_name(direction: str | None) -> bool:
    """True when a normalised direction value names an element."""
    if not direction:
        return False
    return any(token in direction for token in _ELEMENT_TOKENS)


def _norm_text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = _WS_RE.sub(" ", value.strip()).lower()
    return text.replace("→", "->").replace("–", "-").replace("—", "-")


def _norm_speed(value: Any) -> tuple[str, Any] | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return ("num", float(value))
    if isinstance(value, str) and value.strip():
        return ("str", _WS_RE.sub(" ", value.strip()).lower())
    return None


def _norm_phase(value: Any) -> tuple[str, Any] | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return ("num", float(value))
    if isinstance(value, str) and value.strip():
        return ("str", _WS_RE.sub(" ", value.strip()).lower())
    return None


def _side_shape(side: Any, kind: str, label: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate one outgoing/incoming side; returns (normalised, issues)."""
    issues: list[dict[str, Any]] = []
    if not isinstance(side, dict):
        return {}, [{
            "code": f"{kind}_not_object",
            "detail": f"qa.segment_match_gate: {label} {kind} must be an object",
        }]
    required = ("direction", "speed")
    required += ("end_state",) if kind == "outgoing" else ("start_state",)
    normalised: dict[str, Any] = {}
    for key in required:
        if kind == "outgoing" and key == "gesture":
            continue
        value = side.get(key)
        if key == "direction" or key in ("end_state", "start_state"):
            norm = _norm_text(value)
        else:
            norm = _norm_speed(value)
        if norm is None:
            issues.append({
                "code": f"incomplete_{kind}",
                "detail": f"qa.segment_match_gate: {label} {kind} needs a "
                         f"non-empty {key!r}",
            })
        else:
            normalised[key] = norm
    gesture = side.get("gesture")
    if _is_nonempty(gesture):
        normalised["gesture"] = _norm_text(gesture)
    kind_value = side.get("handoff_kind")
    if kind_value is not None:
        if not isinstance(kind_value, str) or not kind_value.strip():
            issues.append({
                "code": "unknown_handoff_kind",
                "detail": f"qa.segment_match_gate: {label} {kind} declares "
                          "an empty 'handoff_kind'",
            })
        else:
            norm_kind = _WS_RE.sub(" ", kind_value.strip()).lower()
            if norm_kind not in HANDOFF_KINDS:
                issues.append({
                    "code": "unknown_handoff_kind",
                    "detail": f"qa.segment_match_gate: {label} {kind} "
                             f"handoff_kind {kind_value!r} is not in the "
                             f"closed vocabulary {list(HANDOFF_KINDS)}",
                })
            else:
                normalised["handoff_kind"] = norm_kind
    element = side.get("element_name")
    if _is_nonempty(element):
        normalised["element_name"] = _norm_text(element)
    if normalised.get("handoff_kind") in _ELEMENT_HANDOFF_KINDS:
        if "element_name" not in normalised:
            issues.append({
                "code": "element_name_missing",
                "detail": f"qa.segment_match_gate: {label} {kind} declares "
                         f"handoff_kind {normalised['handoff_kind']!r} "
                         "but names no 'element_name'",
            })
    elif "element_name" in normalised:
        issues.append({
            "code": "handoff_kind_missing_for_element",
            "detail": f"qa.segment_match_gate: {label} {kind} names "
                     f"element_name {normalised['element_name']!r} but "
                     "declares no element/fabric 'handoff_kind'",
        })
    for key in ("occlusion_direction", "rotation_phase"):
        if side.get(key) is not None:
            if key == "occlusion_direction":
                norm = _norm_text(side.get(key))
            else:
                norm = _norm_phase(side.get(key))
            if norm is None:
                issues.append({
                    "code": f"incomplete_{kind}",
                    "detail": f"qa.segment_match_gate: {label} {kind} "
                             f"declares {key!r} but it is empty or "
                             "unparseable",
                })
            else:
                normalised[key] = norm
    # Direction fields hold direction values only, checked after
    # every direction field has been normalised (occlusion_direction
    # is normalised in the loop above, not before it).
    for key in ("direction", "occlusion_direction"):
        if key in normalised and _direction_contains_element_name(normalised[key]):
            issues.append({
                "code": "direction_contains_element_name",
                "detail": f"qa.segment_match_gate: {label} {kind} {key} "
                         f"{normalised[key]!r} names a hand-off element; "
                         "the element belongs in 'element_name' with "
                         "handoff_kind 'element'/'fabric', and the "
                         "travel belongs in 'direction'",
            })
    return normalised, issues


def _is_nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check_segment_match(plan: Any) -> dict[str, Any]:
    """Judge the cross-segment match chain. Returns a report; never raises for a bad plan."""
    if not isinstance(plan, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "boundaries": [],
            "segments": [],
            "issues": [{
                "code": "plan_not_object",
                "detail": "qa.segment_match_gate: segment plan must be "
                         "an object",
            }],
        }
    segments = plan.get("segments")
    if not isinstance(segments, list) or not segments:
        return {
            "ok": False,
            "verdict": "fail",
            "boundaries": [],
            "segments": [],
            "issues": [{
                "code": "segments_missing",
                "detail": "qa.segment_match_gate: the plan needs a "
                         "non-empty 'segments' list in play order",
            }],
        }

    labels: list[str] = []
    parsed: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        label = f"segment {index + 1}"
        if isinstance(segment, dict):
            ident = segment.get("segment_id", segment.get("id"))
            if _is_nonempty(ident) or isinstance(ident, int):
                label = f"segment {ident}"
        labels.append(label)
        if not isinstance(segment, dict):
            issues.append({
                "code": "segment_not_object",
                "detail": f"qa.segment_match_gate: {label} must be an object",
            })
            parsed.append({})
            continue
        entry: dict[str, Any] = {"label": label}
        for kind in ("outgoing", "incoming"):
            side = segment.get(kind)
            if side is not None:
                normalised, side_issues = _side_shape(side, kind, label)
                entry[kind] = normalised
                issues.extend(side_issues)
        parsed.append(entry)

    if len(segments) == 1:
        segment = segments[0]
        has_out = isinstance(segment, dict) and segment.get("outgoing") is not None
        has_in = isinstance(segment, dict) and segment.get("incoming") is not None
        if not has_out or not has_in:
            code = "single_segment_match_not_recorded"
            detail = ("qa.segment_match_gate: a single segment with no "
                      "outgoing/incoming record proves no cross-segment "
                      "match; it is not_checked, never passed")
        else:
            code = "single_segment_no_boundary"
            detail = ("qa.segment_match_gate: a single segment has no "
                      "neighbour boundary to judge its outgoing/incoming "
                      "record against; it is not_checked, never passed")
        issues.append({"code": code, "detail": detail})
        return {
            "ok": False,
            "verdict": "not_checked",
            "boundaries": [],
            "segments": parsed,
            "issues": issues,
        }

    boundaries: list[dict[str, Any]] = []
    for index in range(len(segments) - 1):
        left, right = parsed[index], parsed[index + 1]
        left_label, right_label = labels[index], labels[index + 1]
        checks: dict[str, Any] = {}
        if "outgoing" not in left:
            issues.append({
                "code": "missing_outgoing",
                "detail": f"qa.segment_match_gate: {left_label} declares "
                         "no 'outgoing' for the boundary into "
                         f"{right_label}; a multi-segment plan with a "
                         "missing match fails",
            })
        if "incoming" not in right:
            issues.append({
                "code": "missing_incoming",
                "detail": f"qa.segment_match_gate: {right_label} declares "
                         "no 'incoming' for the boundary out of "
                         f"{left_label}; a multi-segment plan with a "
                         "missing match fails",
            })
        if "outgoing" in left and "incoming" in right:
            out, inc = left["outgoing"], right["incoming"]
            direction_ok = out.get("direction") is not None \
                and out.get("direction") == inc.get("direction")
            checks["direction"] = direction_ok
            if not direction_ok:
                issues.append({
                    "code": "direction_mismatch",
                    "detail": f"qa.segment_match_gate: {left_label} hands "
                             f"off towards {out.get('direction')!r} but "
                             f"{right_label} takes up towards "
                             f"{inc.get('direction')!r}; the take-up direction "
                             "must equal the outgoing direction",
                })
            speed_ok = out.get("speed") is not None \
                and out.get("speed") == inc.get("speed")
            checks["speed"] = speed_ok
            if not speed_ok:
                issues.append({
                    "code": "speed_mismatch",
                    "detail": f"qa.segment_match_gate: {left_label} hands "
                             f"off at speed {out.get('speed')!r} but "
                             f"{right_label} takes up at speed "
                             f"{inc.get('speed')!r}; the take-up speed must "
                             "equal the outgoing speed",
                })
            state_ok = out.get("end_state") is not None \
                and out.get("end_state") == inc.get("start_state")
            checks["state"] = state_ok
            if not state_ok:
                issues.append({
                    "code": "end_start_state_mismatch",
                    "detail": f"qa.segment_match_gate: {left_label} ends "
                             f"in state {out.get('end_state')!r} but "
                             f"{right_label} starts in state "
                             f"{inc.get('start_state')!r}; the incoming "
                             "start state must equal the outgoing end "
                             "state",
                })
            for key, code in (("rotation_phase", "rotation_phase_mismatch"),
                              ("occlusion_direction", "occlusion_direction_mismatch")):
                if key in out or key in inc:
                    match = key in out and key in inc and out[key] == inc[key]
                    checks[key] = match
                    if not match:
                        issues.append({
                            "code": code,
                            "detail": f"qa.segment_match_gate: {left_label} "
                                     f"and {right_label} disagree on "
                                     f"{key}: outgoing {out.get(key)!r} vs "
                                     f"incoming {inc.get(key)!r}; a phase "
                                     "or occlusion direction declared on "
                                     "one side must be declared and equal "
                                     "on the other",
                        })
                else:
                    checks[key] = None
            if "gesture" in out and "gesture" in inc:
                gesture_ok = out["gesture"] == inc["gesture"]
                checks["gesture"] = gesture_ok
                if not gesture_ok:
                    issues.append({
                        "code": "gesture_mismatch",
                        "detail": f"qa.segment_match_gate: {left_label} "
                                 f"hands off gesture {out['gesture']!r} "
                                 f"but {right_label} continues "
                                 f"{inc['gesture']!r}",
                    })
            else:
                checks["gesture"] = None
            if "handoff_kind" in out or "handoff_kind" in inc:
                kind_ok = "handoff_kind" in out and "handoff_kind" in inc \
                    and out["handoff_kind"] == inc["handoff_kind"]
                checks["handoff_kind"] = kind_ok
                if not kind_ok:
                    issues.append({
                        "code": "handoff_kind_mismatch",
                        "detail": f"qa.segment_match_gate: {left_label} "
                                 f"and {right_label} disagree on "
                                 f"handoff_kind: outgoing "
                                 f"{out.get('handoff_kind')!r} vs incoming "
                                 f"{inc.get('handoff_kind')!r}; a kind "
                                 "declared on one side must be declared "
                                 "and equal on the other",
                    })
            else:
                checks["handoff_kind"] = None
            if out.get("handoff_kind") in _ELEMENT_HANDOFF_KINDS \
                    or inc.get("handoff_kind") in _ELEMENT_HANDOFF_KINDS:
                element_ok = "element_name" in out and "element_name" in inc \
                    and out["element_name"] == inc["element_name"]
                checks["element_name"] = element_ok
                if not element_ok:
                    issues.append({
                        "code": "element_name_mismatch",
                        "detail": f"qa.segment_match_gate: {left_label} "
                                 f"and {right_label} disagree on "
                                 f"element_name: outgoing "
                                 f"{out.get('element_name')!r} vs incoming "
                                 f"{inc.get('element_name')!r}; an "
                                 "element/fabric hand-off must name the "
                                 "same element on both sides",
                    })
            else:
                checks["element_name"] = None
        boundaries.append({
            "from": left_label,
            "to": right_label,
            "checks": checks,
        })

    ok = not issues
    return {
        "ok": ok,
        "verdict": "pass" if ok else "fail",
        "boundaries": boundaries,
        "segments": parsed,
        "issues": issues,
    }


def authorize_segment_match(plan: Any) -> dict[str, Any]:
    """Approve a segment match chain, or refuse it loudly (raises CapabilityError)."""
    report = check_segment_match(plan)
    if not report["ok"]:
        raise CapabilityError(
            "qa.segment_match_gate: segment match refused: "
            + "; ".join(i["detail"] for i in report["issues"])
        )
    return report


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = authorize_segment_match(params.get("plan"))
    report_path = out_dir / "segment_match_gate.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_segment_match_gate_capabilities_once() -> list[str]:
    """Register ``qa.segment_match_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.segment_match_gate",
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
                "Segment match gate: consecutive segments must agree "
                "on the hand-off -- outgoing direction, speed and end "
                "state against incoming direction, speed and start "
                "state, plus rotation phase and occlusion direction "
                "when either side declares them, plus handoff_kind "
                "from a closed vocabulary (element/fabric hand-offs "
                "must name the same element_name on both sides, and "
                "direction holds direction values only -- element "
                "names in direction fail). A missing match in a "
                "multi-segment plan fails; a single segment without a "
                "boundary is not_checked, never passed. Judges plans "
                "only; the prompt_compiler entry/exit state "
                "dictionaries are untouched."
            ),
            line="qa",
        )
    )
    return ["qa.segment_match_gate"]


register_segment_match_gate_capabilities_once()
