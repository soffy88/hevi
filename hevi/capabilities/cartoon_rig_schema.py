"""Procedural cartoon-person rig schema, fake layer (``video.cartoon_rig_schema``).

Contract-only schema. Given a rig plan it compiles the
contract for a procedurally posed cartoon person: the joint
set, the two-bone arm rule, the pose list, the prop list,
and the time-only update rule. The update rule is the load
bearing part: a frame's pose must depend only on its time
value, so rendering may start mid-shot; any plan that keeps
state across frames fails. This module executes nothing:
``executed_here`` is always false, ``rendered_here`` is
always false, and ``output_file`` is always null. No rig is
built and no frame is rendered here. The schema is a format
reference only and carries no affiliation with any named
creator. See ANIMATION_SKILLS_ATTRIBUTION.md.
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

# Core joints, restated in hevi's own words: a spine chain
# plus a head, with an arm and a leg joint on each side.
CORE_JOINTS = ("pelvis", "spine", "chest", "neck", "head")
ARM_JOINTS = ("arm_l", "arm_r")
LEG_JOINTS = ("leg_l", "leg_r")


def _fail(message: str) -> None:
    raise CapabilityError(message)


def compile_cartoon_rig_contract(plan: Any) -> dict[str, Any]:
    """Compile a cartoon rig contract from a plan.

    Raises :class:`CapabilityError` on a malformed plan. The
    returned contract always carries ``executed_here: false``,
    ``rendered_here: false``, and ``output_file: null``:
    nothing is built or rendered here.
    """
    if not isinstance(plan, dict):
        _fail("cartoon rig plan must be a JSON object")
    if plan.get("affiliation_claimed") is True:
        _fail("the rig schema carries no affiliation with any named creator")
    rig = plan.get("rig")
    if not isinstance(rig, dict):
        _fail("cartoon rig plan must declare a rig object")
    joints = rig.get("joints")
    if not isinstance(joints, list) or not joints:
        _fail("rig must declare a non-empty joints list")
    joint_set = set(joints)
    for core in CORE_JOINTS:
        if core not in joint_set:
            _fail(f"rig joints must include core joint {core!r}")
    if not any(joint in joint_set for joint in ARM_JOINTS):
        _fail("rig joints must include at least one arm joint")
    if not any(joint in joint_set for joint in LEG_JOINTS):
        _fail("rig joints must include at least one leg joint")
    if rig.get("arms_ik") != "two_bone":
        _fail("arm posing must declare two-bone inverse kinematics")
    if plan.get("update_rule") != "time_only":
        _fail(
            "the update rule must be 'time_only': a frame's pose "
            "depends only on its time value, never on kept state"
        )
    poses = plan.get("poses")
    if not isinstance(poses, list) or not poses:
        _fail("cartoon rig plan must declare a non-empty poses list")
    poses_out: list[dict[str, Any]] = []
    for index, pose in enumerate(poses):
        if not isinstance(pose, dict):
            _fail(f"poses[{index}] must be an object")
        name = pose.get("name")
        if not isinstance(name, str) or not name.strip():
            _fail(f"poses[{index}] must name itself")
        pose_joints = pose.get("joints")
        if not isinstance(pose_joints, dict) or not pose_joints:
            _fail(f"poses[{index}] must declare joint values")
        for joint in pose_joints:
            if joint not in joint_set:
                _fail(f"poses[{index}] names undeclared joint {joint!r}")
        poses_out.append({"name": name, "joints": dict(pose_joints)})
    props = plan.get("props", [])
    if not isinstance(props, list):
        _fail("props must be a list when present")
    for index, prop in enumerate(props):
        if not isinstance(prop, str) or not prop.strip():
            _fail(f"props[{index}] must be a non-empty name")
    mouth = plan.get("mouth_control", False)
    return {
        "joints": list(joints),
        "arms_ik": "two_bone",
        "poses": poses_out,
        "pose_count": len(poses_out),
        "props": list(props),
        "mouth_control": bool(mouth),
        "update_rule": "time_only",
        "affiliation": "none; format reference only",
        "executed_here": False,
        "rendered_here": False,
        "output_file": None,
        "render_required": "separate case; no rendering here",
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_cartoon_rig_contract(params.get("plan"))
    contract_path = out_dir / "cartoon_rig_contract.json"
    contract_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={"contract_json": str(contract_path), "executed_here": False},
    )


def register_cartoon_rig_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.cartoon_rig_schema",
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
            layer="obase",
            description=(
                "Cartoon rig schema (contract only): joint set, "
                "two-bone arm rule, pose list, props, and the "
                "time-only update rule; nothing is built or "
                "rendered here, and no creator affiliation is "
                "claimed."
            ),
        )
    )
    return ["video.cartoon_rig_schema"]


__all__ = [
    "compile_cartoon_rig_contract",
    "register_cartoon_rig_schema_capabilities_once",
]
