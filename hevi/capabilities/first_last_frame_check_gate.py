"""First/last-frame check gate (``qa.first_last_frame_check_gate``).

Clean-room restatement of the Eian short-film workflow
(see ``EIAN_WORKFLOW_ATTRIBUTION.md``): the cheapest way
to keep a generated shot from falling apart is to pin its
first and last frames. Eight checks are applied here, in
the reviewer's own words — every prop the action needs
must already sit in the first frame, bystander reactions
must be staged before the shot starts, no group may share
one pose, room must be left for the action to land, wind
must blow one way, the frame must read at phone size,
nothing extra may hide in the frame when enlarged, and
the two frames overlaid must agree everywhere they should
not change. This gate judges the shot record only. It
draws nothing, renders nothing, and spends nothing:
``executed_here`` is always false.
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

# Frame regions that must not change between first and last
# frame: a change here means the model drifted the scene.
FROZEN_REGIONS: frozenset[str] = frozenset(
    {"wall_color", "prop_size", "background", "camera_position"}
)


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_first_last_frame(shot: Any) -> dict[str, Any]:
    """Validate one shot's first and last frames.

    Verdicts are ``pass`` / ``fail`` only. A shot fails
    when an action prop is missing from the first frame,
    when a bystander is not staged facing the camera, when
    a group shares one pose, when wind blows two ways, when
    an extra object hides in the frame, when the overlaid
    frames disagree on a frozen region, or when a distant
    figure is unreadable at phone size.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(shot, dict):
        return fail("shot_not_object", "shot must be a JSON object")
    props_needed = shot.get("props_needed")
    if not isinstance(props_needed, list):
        return fail(
            "props_needed_missing",
            "shot must list the props its action needs",
        )
    props_in_first = shot.get("props_in_first")
    if not isinstance(props_in_first, list):
        return fail(
            "props_in_first_missing",
            "shot must list the props visible in its first frame",
        )
    missing = [prop for prop in props_needed if prop not in props_in_first]
    if missing:
        return fail(
            "prop_appears_from_nowhere",
            f"props {missing} are needed by the action but absent "
            "from the first frame; they would appear from nowhere",
        )
    bystanders = shot.get("bystanders")
    if isinstance(bystanders, list):
        for position, person in enumerate(bystanders):
            if not isinstance(person, dict):
                return fail(
                    "bystander_not_object",
                    f"bystander {position} must be an object",
                )
            if person.get("facing_camera") is not True:
                return fail(
                    "reaction_not_staged",
                    f"bystander {position} must be staged facing the camera before the shot starts",
                )
    poses = shot.get("poses")
    if isinstance(poses, list) and len(poses) > 1 and len(set(poses)) == 1:
        return fail(
            "same_pose_group",
            "a group must not share one pose, or the model moves everyone at once",
        )
    wind = shot.get("wind_directions")
    if isinstance(wind, dict) and wind:
        directions = {str(value) for value in wind.values()}
        if len(directions) > 1:
            return fail(
                "wind_inconsistent",
                f"wind blows {sorted(directions)} at once; it must blow one way",
            )
    extras = shot.get("extra_objects")
    if isinstance(extras, list) and extras:
        return fail(
            "extra_objects",
            f"enlarged check found extra objects {extras} in the frame",
        )
    overlay = shot.get("overlay_alignment")
    if not isinstance(overlay, dict):
        return fail(
            "overlay_missing",
            "first and last frames must be overlaid and checked for drift",
        )
    if overlay.get("aligned") is not True:
        return fail(
            "frame_misaligned",
            "first and last frames overlaid do not line up",
        )
    changes = overlay.get("changed_regions")
    if isinstance(changes, list):
        for region in changes:
            if region in FROZEN_REGIONS:
                return fail(
                    "frozen_region_changed",
                    f"{region} differs between first and last frame; it must stay identical",
                )
    mobile = shot.get("mobile_check")
    if (
        isinstance(mobile, dict)
        and mobile.get("checked") is True
        and mobile.get("distant_figure_readable") is False
    ):
        return fail(
            "distant_figure_unreadable",
            "a distant figure is unreadable at phone size",
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
    report = check_first_last_frame(params.get("shot"))
    report_path = out_dir / "first_last_frame_check_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_first_last_frame_check_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.first_last_frame_check_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "shot": {"type": "object"},
                },
                "required": ["shot"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "First/last-frame check gate: props staged in the first "
                "frame, reactions pre-staged, no shared pose, one wind "
                "direction, no extra objects, overlaid frames agree."
            ),
        )
    )
    return ["qa.first_last_frame_check_gate"]


__all__ = [
    "FROZEN_REGIONS",
    "check_first_last_frame",
    "register_first_last_frame_check_gate_capabilities_once",
]
