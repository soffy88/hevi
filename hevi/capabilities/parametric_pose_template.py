"""Parametric pose template (``qa.parametric_pose_template``).

Clean-room rewrite of the parameterised-pose *idea* in
``hevi-vs-oyasumi-gamedev.md`` item 8 (from the oyasumi-gamedev.com
tool pages, restated in the report's own words): a pose is a
parameterised action template plus kinematic constraints. Slider
numbers (timing, speed, stride, style variants) drive joint
angles, built-in body rules keep the result human -- arms swing
against legs, waist twists against chest -- and the same numbers
reproduce the same pose on any figure. Only the idea is taken
here. The source tool's internal construction, its parameter
defaults, and its file format (VRMA) were never inspected and
are not reproduced: this module outputs hevi's own pose JSON,
checks caller-declared ranges and constraints, and renders a
2D stick-figure silhouette for visual checking. No VRMA is read
or written, and no 3D model is touched.

What it checks and builds:

1. Every parameter value lies inside its caller-declared range;
   out-of-range values fail.
2. Counter-swing: when arm and leg swing angles are both
   declared, the left arm must swing with the right leg and the
   right arm with the left leg (same sign on each diagonal).
   A same-side swing fails.
3. Counter-twist: when waist and chest twist angles are both
   declared, they must twist in opposite directions. Same-side
   twist fails.
4. The template declares a gaze direction; without one it fails.
5. The built pose JSON records the action, the parameters, the
   joint angles, the derived part orientations (gaze / face /
   chest / waist / feet), and ``synthetic: true``. A stick-figure
   silhouette is rendered from the joint angles by plain 2D
   forward kinematics, so the pose can be seen without any
   model.

Joint names and angle ranges are caller-declared; this module
adds no anatomical defaults. This module judges and builds
records only. It never calls a model, never touches a key or a
budget.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

# Segment lengths for the 2D stick figure, in pixels. These are
# drawing constants for the silhouette check only -- not body
# measurements, not site numbers, and never used to judge a pose.
_SEGMENTS = {
    "pelvis_to_chest": 46,
    "chest_to_head": 26,
    "upper_arm": 30,
    "lower_arm": 28,
    "upper_leg": 38,
    "lower_leg": 38,
}


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.parametric_pose_template: {detail}"}
    issue.update(extra)
    return issue


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def build_pose_template(spec: Any) -> dict[str, Any]:
    """Build and check one parametric pose. Returns pose JSON content.

    ``spec``: {template_name, action, parameters: {name: value},
    ranges: {name: [min, max]}, joints: {joint: angle_deg},
    constraints: [constraint names to enforce], gaze_direction:
    toward/away/neutral}. Constraint names are caller-declared;
    the engine enforces ``counter_swing`` and ``counter_twist``
    when named, and rejects unknown constraint names.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(spec, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "issues": [_issue("spec_not_object", "pose spec must be an object")],
        }
    name = spec.get("template_name")
    if not isinstance(name, str) or not name.strip():
        issues.append(_issue("template_name_missing", "spec must name its template"))
    action = spec.get("action")
    if not isinstance(action, str) or not action.strip():
        issues.append(_issue("action_missing", "spec must name its action"))
    parameters = spec.get("parameters")
    if not isinstance(parameters, dict):
        issues.append(_issue("parameters_missing", "spec must declare parameters"))
        parameters = {}
    ranges = spec.get("ranges")
    if not isinstance(ranges, dict):
        issues.append(_issue("ranges_missing", "spec must declare parameter ranges"))
        ranges = {}
    for param, value in parameters.items():
        bounds = ranges.get(param)
        if not (isinstance(bounds, list) and len(bounds) == 2 and all(_is_number(b) for b in bounds)):
            issues.append(
                _issue(
                    "range_undeclared",
                    f"parameter {param!r} has no caller-declared [min, max] range",
                    parameter=param,
                )
            )
        elif not (bounds[0] <= value <= bounds[1]):
            issues.append(
                _issue(
                    "parameter_out_of_range",
                    f"parameter {param!r} value {value} outside caller range "
                    f"[{bounds[0]}, {bounds[1]}]",
                    parameter=param,
                )
            )
    joints = spec.get("joints")
    if not isinstance(joints, dict) or not joints:
        issues.append(_issue("joints_missing", "spec must declare joint angles in degrees"))
        joints = {}
    for joint, angle in joints.items():
        if not _is_number(angle):
            issues.append(
                _issue("joint_angle_invalid", f"joint {joint!r} angle must be a number")
            )
    constraints = spec.get("constraints") or []
    if not isinstance(constraints, list):
        issues.append(_issue("constraints_invalid", "constraints must be a list"))
        constraints = []
    for constraint in constraints:
        if constraint not in ("counter_swing", "counter_twist"):
            issues.append(
                _issue("constraint_unknown", f"unknown constraint {constraint!r}")
            )
    if "counter_swing" in constraints:
        arm_l = joints.get("shoulder_l")
        arm_r = joints.get("shoulder_r")
        leg_l = joints.get("hip_l")
        leg_r = joints.get("hip_r")
        if all(_is_number(v) for v in (arm_l, arm_r, leg_l, leg_r)):
            if (arm_l > 0) == (leg_r > 0) and arm_l != 0 and leg_r != 0:
                pass
            elif arm_l == 0 or leg_r == 0:
                pass
            else:
                issues.append(
                    _issue(
                        "counter_swing_violated",
                        "left arm must swing with the right leg (same "
                        "sign); arms swinging with the same-side leg "
                        "breaks the counter-swing rule",
                    )
                )
            if (arm_r > 0) == (leg_l > 0) and arm_r != 0 and leg_l != 0:
                pass
            elif arm_r == 0 or leg_l == 0:
                pass
            else:
                issues.append(
                    _issue(
                        "counter_swing_violated",
                        "right arm must swing with the left leg (same "
                        "sign)",
                    )
                )
    if "counter_twist" in constraints:
        waist = joints.get("waist_twist")
        chest = joints.get("chest_twist")
        if _is_number(waist) and _is_number(chest) and waist != 0 and chest != 0:
            if (waist > 0) == (chest > 0):
                issues.append(
                    _issue(
                        "counter_twist_violated",
                        "waist and chest must twist in opposite directions",
                    )
                )
    gaze = spec.get("gaze_direction")
    if gaze not in ("toward", "away", "neutral"):
        issues.append(
            _issue(
                "gaze_undeclared",
                f"spec must declare gaze_direction toward/away/neutral, got {gaze!r}",
            )
        )
    if issues:
        return {"ok": False, "verdict": "fail", "issues": issues}
    orientations = {
        "gaze": gaze,
        "face": spec.get("face_orientation", gaze),
        "chest": "toward" if _is_number(joints.get("chest_twist")) and joints["chest_twist"] >= 0 else "away",
        "waist": "toward" if _is_number(joints.get("waist_twist")) and joints["waist_twist"] >= 0 else "away",
        "feet": spec.get("feet_orientation", "neutral"),
    }
    pose = {
        "template_name": name,
        "action": action,
        "parameters": parameters,
        "ranges": ranges,
        "joints_deg": joints,
        "constraints_checked": sorted(set(constraints)),
        "orientations": orientations,
        "synthetic": True,
    }
    return {"ok": True, "verdict": "pass", "issues": [], "pose": pose}


def _point(origin: tuple[float, float], length: float, angle_deg: float) -> tuple[float, float]:
    angle = math.radians(angle_deg)
    return (origin[0] + length * math.sin(angle), origin[1] - length * math.cos(angle))


def render_pose_silhouette(pose: dict[str, Any], out_path: Path) -> Path:
    """Render a 2D stick-figure silhouette from joint angles (side view)."""
    joints = pose["joints_deg"]
    width, height = 200, 220
    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    pelvis = (100.0, 150.0)
    chest = _point(pelvis, _SEGMENTS["pelvis_to_chest"], joints.get("spine_lean", 0))
    head = _point(chest, _SEGMENTS["chest_to_head"], joints.get("spine_lean", 0) + joints.get("head_tilt", 0))
    shoulder = chest
    elbow_l = _point(shoulder, _SEGMENTS["upper_arm"], joints.get("shoulder_l", 0))
    hand_l = _point(elbow_l, _SEGMENTS["lower_arm"], joints.get("shoulder_l", 0) + joints.get("elbow_l", 0))
    elbow_r = _point(shoulder, _SEGMENTS["upper_arm"], joints.get("shoulder_r", 0))
    hand_r = _point(elbow_r, _SEGMENTS["lower_arm"], joints.get("shoulder_r", 0) + joints.get("elbow_r", 0))
    knee_l = _point(pelvis, _SEGMENTS["upper_leg"], joints.get("hip_l", 0))
    foot_l = _point(knee_l, _SEGMENTS["lower_leg"], joints.get("hip_l", 0) + joints.get("knee_l", 0))
    knee_r = _point(pelvis, _SEGMENTS["upper_leg"], joints.get("hip_r", 0))
    foot_r = _point(knee_r, _SEGMENTS["lower_leg"], joints.get("hip_r", 0) + joints.get("knee_r", 0))
    for start, end in (
        (pelvis, chest), (chest, head),
        (shoulder, elbow_l), (elbow_l, hand_l),
        (shoulder, elbow_r), (elbow_r, hand_r),
        (pelvis, knee_l), (knee_l, foot_l),
        (pelvis, knee_r), (knee_r, foot_r),
    ):
        draw.line([start, end], fill=(0, 0, 0), width=4)
    for joint_point in (pelvis, chest, head, elbow_l, hand_l, elbow_r, hand_r, knee_l, foot_l, knee_r, foot_r):
        x, y = joint_point
        draw.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(0, 0, 0))
    image.save(out_path)
    return out_path


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result = build_pose_template(params.get("spec"))
    if result["ok"]:
        pose_path = out_dir / "pose_template.json"
        pose_path.write_text(
            json.dumps(result["pose"], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        silhouette = render_pose_silhouette(result["pose"], out_dir / "pose_silhouette.png")
        report = {
            **result,
            "pose_json": str(pose_path),
            "silhouette": silhouette.name,
            "silhouette_sha256": hashlib.sha256(silhouette.read_bytes()).hexdigest(),
        }
    else:
        report = result
    report_path = out_dir / "parametric_pose_template.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_parametric_pose_template_capabilities_once() -> list[str]:
    """Register ``qa.parametric_pose_template`` on the registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.parametric_pose_template",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {"spec": {"type": "object"}},
                "required": ["spec"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Parametric pose template: caller-declared parameter "
                "ranges and kinematic constraints (counter-swing, "
                "counter-twist) checked, gaze declared, pose emitted "
                "as hevi pose JSON with a 2D stick-figure silhouette. "
                "No VRMA, no 3D model. Judges and builds records only."
            ),
            line="qa",
        )
    )
    return ["qa.parametric_pose_template"]


register_parametric_pose_template_capabilities_once()
