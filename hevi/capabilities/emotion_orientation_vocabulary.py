"""Emotion-to-orientation vocabulary gate (``qa.emotion_orientation_vocabulary``).

Clean-room rewrite of the posture method in
``hevi-vs-oyasumi-gamedev.md`` item 4 (from the oyasumi-gamedev.com
manga-research series, restated in the report's own words): an
emotion is first translated into a direction of action -- approach,
retreat, open up, close in, or freeze -- and that direction is
then distributed over the body in the order gaze, face, chest,
waist, feet. The upper body carries the immediate feeling, the
lower body carries the next action. When every part points the
same way the emotion reads directly and strongly; when one part
points elsewhere a compound emotion appears (hesitation, shyness,
and the like), and that single deviation is where the compound
reading starts. When the face and the body contradict each other,
the reader's reading of the face is pulled away by the body. A
faceless silhouette must still read: its direction of action
should be legible without a face.

This gate judges a pose plan -- records supplied by the caller --
not a picture. It checks:

1. The plan declares an action direction from the closed
   vocabulary (approach / retreat / open / contract / freeze).
2. All five parts (gaze, face, chest, waist, feet) declare an
   orientation (toward / away / neutral).
3. A non-uniform allocation (parts pointing different ways) must
   declare its intent (a compound emotion or a misalignment
   intent); undeclared deviation fails.
4. A face/body contradiction (the face pointing one way while
   chest and waist both point the other) must declare the compound
   emotion by name; anything weaker fails.
5. A faceless pose (``face_visible: false``) must declare its
   silhouette readability basis; without one it fails.

Orientation words are caller-declared from the closed
vocabularies below. This module judges plans only. It never
generates, never calls a model, never touches a budget.
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

DIRECTIONS = ("approach", "retreat", "open", "contract", "freeze")
ORIENTATIONS = ("toward", "away", "neutral")
PARTS = ("gaze", "face", "chest", "waist", "feet")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.emotion_orientation_vocabulary: {detail}"}
    issue.update(extra)
    return issue


def check_emotion_orientation(plan: Any) -> dict[str, Any]:
    """Judge one pose plan. Returns ``ok`` / ``verdict`` / ``issues``.

    ``plan`` is an object with ``action_direction`` (one of the five
    directions), ``orientations`` (an object with all five parts),
    ``face_visible`` (bool), optional ``composite_emotion``,
    optional ``misalignment_intent`` and, for faceless poses,
    ``silhouette_readability``.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "issues": [_issue("plan_not_object", "pose plan must be an object")],
        }
    direction = plan.get("action_direction")
    if direction not in DIRECTIONS:
        issues.append(
            _issue(
                "direction_undeclared",
                "pose plan must declare an action direction "
                f"approach/retreat/open/contract/freeze, got {direction!r}",
            )
        )
    orientations = plan.get("orientations")
    allocation: dict[str, Any] = {}
    if not isinstance(orientations, dict):
        issues.append(
            _issue("orientations_missing", "pose plan must declare orientations for all five parts")
        )
    else:
        for part in PARTS:
            value = orientations.get(part)
            if value not in ORIENTATIONS:
                issues.append(
                    _issue(
                        "orientation_undeclared",
                        f"part {part!r} must declare an orientation "
                        f"toward/away/neutral, got {value!r}",
                        part=part,
                    )
                )
            else:
                allocation[part] = value
    face_visible = plan.get("face_visible", True)
    if not isinstance(face_visible, bool):
        issues.append(
            _issue("face_visible_invalid", "face_visible must be a boolean")
        )
        face_visible = True
    composite = plan.get("composite_emotion")
    intent = plan.get("misalignment_intent")
    declared_intent = (isinstance(composite, str) and composite.strip()) or (
        isinstance(intent, str) and intent.strip()
    )
    if len(allocation) == len(PARTS):
        values = list(allocation.values())
        if len(set(values)) > 1 and not declared_intent:
            issues.append(
                _issue(
                    "misalignment_undeclared",
                    "body parts point different ways; a non-uniform "
                    "allocation reads as a compound emotion and must "
                    "declare its intent (composite_emotion or "
                    "misalignment_intent)",
                )
            )
        face = allocation.get("face")
        chest = allocation.get("chest")
        waist = allocation.get("waist")
        if (
            face_visible
            and face in ("toward", "away")
            and chest == waist
            and chest in ("toward", "away")
            and face != chest
        ):
            if not (isinstance(composite, str) and composite.strip()):
                issues.append(
                    _issue(
                        "face_body_conflict_undeclared",
                        "face points one way while chest and waist both "
                        "point the other; the reader's reading of the "
                        "face is pulled by the body, so the compound "
                        "emotion must be declared by name",
                    )
                )
    if not face_visible:
        basis = plan.get("silhouette_readability")
        if not isinstance(basis, str) or not basis.strip():
            issues.append(
                _issue(
                    "silhouette_basis_missing",
                    "a faceless pose must declare its silhouette "
                    "readability basis: how the direction of action "
                    "reads without a face",
                )
            )
    verdict = "fail" if issues else "pass"
    return {"ok": verdict == "pass", "verdict": verdict, "issues": issues}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_emotion_orientation(params.get("plan"))
    report_path = out_dir / "emotion_orientation_vocabulary.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_emotion_orientation_capabilities_once() -> list[str]:
    """Register ``qa.emotion_orientation_vocabulary`` on the registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.emotion_orientation_vocabulary",
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
                "Emotion-to-orientation vocabulary gate: an action "
                "direction plus gaze/face/chest/waist/feet orientations; "
                "non-uniform allocations and face/body contradictions "
                "must declare their compound intent, and faceless poses "
                "must declare a silhouette readability basis. Judges "
                "plans only."
            ),
            line="qa",
        )
    )
    return ["qa.emotion_orientation_vocabulary"]


register_emotion_orientation_capabilities_once()
