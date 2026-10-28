"""Gesture risk gate for motion beats and digital-human action specs
(``video.gesture_risk_gate``).

This gate sits on top of ``video.motion_beat_chart`` and the
talking-head action spec: it does not render, rig or drive any
digital human (no MuseTalk connection is made here), it only gates
a written gesture plan before anyone spends generation budget on it.

Method ideas borrowed, text self-written, from
Pluviobyte/awesome-talking-head-skills (MIT, 2026-10-27): a good
talking-head performance uses a small fixed gesture vocabulary, a
fixed vertical range, and gestures that land on stressed lines.
The three risk tiers below are the gate's own wording of that
idea; no creator's appearance, clothing, scene or verbatim lines
are described, stored or used anywhere in this module.

Red lines, stated in the module so a caller cannot miss them:
- Only written gesture specs are read. No sample video is read,
  stored, copied or fed to any generator by this module; this
  module contains no sample at all.
- No creator likeness, face, clothing or verbatim script is used.
  Sample material belongs to its original creators; a removal
  request for any sample would be honoured by deleting the
  sample, and this module has nothing to delete.
- A high-tier gesture is a warning, not a ban: the caller decides
  whether to take the risk, after reading the downgrade
  suggestion attached to it.

Rules enforced (problems fail the plan, warnings do not):
1. Every gesture beat must declare a tier: low, medium or high.
   A beat with no tier, or an unknown tier, fails and is named.
2. Low tier: hands off-frame, a single hand rising from a low
   position, or expression only. Medium tier: both hands opening
   symmetrically, tossed outward or framing, with no precise
   finger shape required. High tier: two index fingers, pinched
   fingertips, a spread-fingers close-up, or interlocked bent
   fingers -- the shapes most likely to collapse in generation.
3. At most 7 distinct gesture names per plan. The 8th and later
   distinct names fail and are named.
4. The gesture range is chest to cheek (plus off-frame and low
   below-chest entries). Any zone outside that band fails.
5. Every gesture must anchor to a stressed line or punctuation
   point in the script. A gesture with no anchor fails.
6. The opening structure must be declared: person_first or
   evidence_first. For evidence_first the first frame must be
   evidence, and the plan must state how the cut away from it
   covers the generation seam; otherwise the plan fails.
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

TIERS = ("low", "medium", "high")
# Vertical band for hand movement. "off_frame" means the hands are
# not in the picture at all; "low" means below chest height.
ALLOWED_ZONES = ("off_frame", "low", "chest", "chest_to_cheek", "cheek")
MAX_DISTINCT_GESTURES = 7
OPENING_STRUCTURES = ("person_first", "evidence_first")

_DOWNGRADE_SUGGESTION = (
    "downgrade to a low-tier beat (hands off-frame, expression "
    "carries the line) or a medium-tier beat (both hands opening "
    "symmetrically at chest height, no precise finger shape)"
)


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _normalise_gesture(beat: dict[str, Any]) -> dict[str, Any]:
    """Return {name, tier, zone, anchor} for one beat's gesture.

    Two input shapes are accepted: a flat beat (gesture is the
    name string, tier/zone/anchor are sibling fields) and a nested
    beat (gesture is an object with name/tier/zone/anchor keys).
    Missing keys become None so validation can name them.
    """
    raw = beat.get("gesture")
    if isinstance(raw, dict):
        return {
            "name": raw.get("name"),
            "tier": raw.get("tier"),
            "zone": raw.get("zone"),
            "anchor": raw.get("anchor"),
        }
    return {
        "name": raw if isinstance(raw, str) else None,
        "tier": beat.get("tier"),
        "zone": beat.get("zone"),
        "anchor": beat.get("anchor"),
    }


def validate_gesture_beat(beat: dict[str, Any], index: int) -> list[str]:
    """Check one gesture beat; return its problems, if any."""
    problems: list[str] = []
    if not isinstance(beat, dict):
        return [f"beat {index} must be an object"]
    start, end = beat.get("start_sec"), beat.get("end_sec")
    if _is_num(start) and _is_num(end):
        if float(start) < 0 or float(end) <= float(start):
            problems.append(
                f"beat {index} has an invalid time window ({start} to {end})"
            )
    else:
        problems.append(f"beat {index} needs numeric start_sec/end_sec")
    gesture = _normalise_gesture(beat)
    name = gesture["name"]
    if not isinstance(name, str) or not name.strip():
        problems.append(f"beat {index} gesture name is missing or empty")
    tier = gesture["tier"]
    if tier not in TIERS:
        problems.append(
            f"beat {index} gesture {name!r} has no tier (must be one of "
            f"{list(TIERS)}); an un-tiered gesture fails"
        )
    zone = gesture["zone"]
    if zone not in ALLOWED_ZONES:
        problems.append(
            f"beat {index} gesture {name!r} zone {zone!r} is outside the "
            f"allowed band {list(ALLOWED_ZONES)} (chest to cheek, plus "
            "off-frame and low entries)"
        )
    anchor = gesture["anchor"]
    if not isinstance(anchor, str) or not anchor.strip():
        problems.append(
            f"beat {index} gesture {name!r} has no anchor: every gesture "
            "must land on a stressed line or punctuation point"
        )
    return problems


def _validate_opening(plan: dict[str, Any]) -> list[str]:
    """Check the declared opening structure; return problems."""
    problems: list[str] = []
    structure = plan.get("opening_structure")
    if structure not in OPENING_STRUCTURES:
        problems.append(
            f"opening_structure {structure!r} is missing or unknown "
            f"(must be one of {list(OPENING_STRUCTURES)})"
        )
        return problems
    first_frame = plan.get("first_frame")
    if structure == "evidence_first":
        if first_frame != "evidence":
            problems.append(
                "evidence_first opening requires first_frame 'evidence', "
                f"got {first_frame!r}"
            )
        note = plan.get("seam_cover_note")
        if not isinstance(note, str) or not note.strip():
            problems.append(
                "evidence_first opening requires a seam_cover_note "
                "stating how the cut away from the evidence frame "
                "covers the generation seam"
            )
    elif structure == "person_first":
        if first_frame is not None and first_frame != "person":
            problems.append(
                "person_first opening requires first_frame 'person' "
                f"when declared, got {first_frame!r}"
            )
    return problems


def gate_gestures(plan: dict[str, Any]) -> dict[str, Any]:
    """Gate a gesture plan: tiers, vocabulary size, range, anchors, opening.

    High-tier gestures produce warnings plus a downgrade
    suggestion each, but do not fail the plan: the caller decides
    whether to take the risk. Every other problem fails it.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("video.gesture_risk_gate: plan must be an object")
    beats = plan.get("beats")
    if not isinstance(beats, list) or not beats:
        raise CapabilityError(
            "video.gesture_risk_gate: beats must be a non-empty list"
        )
    problems: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    suggestions: list[dict[str, Any]] = []
    tier_counts: dict[str, int] = {tier: 0 for tier in TIERS}
    distinct: list[str] = []
    for i, beat in enumerate(beats):
        for detail in validate_gesture_beat(beat, i):
            problems.append(
                {"beat": i, "kind": "gesture", "detail": detail}
            )
        if isinstance(beat, dict):
            gesture = _normalise_gesture(beat)
            name = gesture["name"]
            if isinstance(name, str) and name.strip() and name not in distinct:
                distinct.append(name)
            tier = gesture["tier"]
            if tier in TIERS:
                tier_counts[tier] += 1
                if tier == "high":
                    warnings.append({
                        "beat": i,
                        "kind": "high_tier_gesture",
                        "detail": (
                            f"beat {i} gesture {name!r} is high tier: "
                            "precise finger shapes are the most likely "
                            "to collapse in generation"
                        ),
                    })
                    suggestions.append({
                        "beat": i,
                        "gesture": name,
                        "tier": "high",
                        "suggestion": _DOWNGRADE_SUGGESTION,
                    })
    extras = distinct[MAX_DISTINCT_GESTURES:]
    if extras:
        problems.append({
            "beat": None,
            "kind": "vocabulary_overflow",
            "detail": (
                f"plan uses {len(distinct)} distinct gestures "
                f"(limit {MAX_DISTINCT_GESTURES}); excess gestures: {extras}"
            ),
        })
    for detail in _validate_opening(plan):
        problems.append({"beat": None, "kind": "opening", "detail": detail})
    return {
        "capability": "video.gesture_risk_gate",
        "beat_count": len(beats),
        "distinct_gestures": distinct,
        "distinct_gesture_count": len(distinct),
        "max_distinct_gestures": MAX_DISTINCT_GESTURES,
        "tier_counts": tier_counts,
        "problems": problems,
        "warnings": warnings,
        "suggestions": suggestions,
        "verdict": "fail" if problems else "pass",
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    plan = params.get("plan")
    if not isinstance(plan, dict):
        raise CapabilityError("video.gesture_risk_gate: plan must be an object")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = gate_gestures(plan)
    report_path = out_dir / "gesture_risk_gate_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_gesture_risk_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.gesture_risk_gate",
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
                "Gesture risk gate for motion beats and digital-human "
                "action specs: every gesture declares a tier (low, "
                "medium, high), at most 7 distinct gestures per plan, "
                "hands stay in the chest-to-cheek band (plus "
                "off-frame/low entries), every gesture anchors to a "
                "stressed line, and the opening structure "
                "(person_first or evidence_first) is declared. "
                "High-tier gestures warn with a downgrade suggestion "
                "but do not fail. Written specs only: no sample "
                "video, no creator likeness, no MuseTalk rig "
                "connection; renders nothing itself."
            ),
            line="video",
        )
    )
    return ["video.gesture_risk_gate"]


register_gesture_risk_gate_capabilities_once()
