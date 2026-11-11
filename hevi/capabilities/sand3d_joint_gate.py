"""Joint and articulation gate (``qa.sand3d_joint_gate``).

A sand3d-style joint names a child part, the part it hangs on,
its kind, and its axis. Four kinds exist: ``revolute`` turns
within a range in degrees, ``prismatic`` slides within a range
in the program's unit, ``continuous`` turns without end, and
``free`` moves freely. Ranged kinds must carry a ``range``
``(low, high)`` with ``low < high``; endless kinds take no
range at all. A joint without a name, child, mount, kind, or
axis fails, as does a range on an endless joint or a missing
range on a ranged joint.

Clean-room restatement of the Sandflow-ai/sand3d method (see
``SAND3D_ATTRIBUTION.md``); no upstream code appears here.
This gate judges joint descriptions only; it never runs
Blender or any sand3d code. Real execution needs a separate
py3.13 + bpy 5.2 environment and is a separate work item.
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

JOINT_KINDS: frozenset[str] = frozenset({"revolute", "prismatic", "continuous", "free"})
RANGED_KINDS: frozenset[str] = frozenset({"revolute", "prismatic"})
ENDLESS_KINDS: frozenset[str] = frozenset({"continuous", "free"})


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_sand3d_joint(joints: Any) -> dict[str, Any]:
    """Validate a sand3d-style joint list.

    Verdicts are ``pass`` / ``fail`` only. The list fails when
    it is not a non-empty list, when any joint is not an object,
    when a joint lacks a name, child, mount, kind, or axis, when
    the kind is outside the four known kinds, when a ranged
    joint (revolute, prismatic) lacks a ``(low, high)`` range
    with ``low < high``, or when an endless joint (continuous,
    free) carries a range.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(joints, list) or not joints:
        return fail("joints_missing", "joint list must be a non-empty list")
    for position, joint in enumerate(joints):
        if not isinstance(joint, dict):
            return fail(
                "joint_not_object",
                f"joint {position} must be an object",
            )
        for field in ("name", "child", "on", "kind", "axis"):
            value = joint.get(field)
            if not isinstance(value, str) or not value:
                return fail(
                    "joint_field_missing",
                    f"joint {position} must carry a non-empty {field!r}",
                )
        kind = joint["kind"]
        if kind not in JOINT_KINDS:
            return fail(
                "joint_kind_unknown",
                f"joint {position} kind {kind!r} is none of revolute, prismatic, continuous, free",
            )
        if kind in RANGED_KINDS:
            low_high = joint.get("range")
            if (
                not isinstance(low_high, (list, tuple))
                or len(low_high) != 2
                or not _is_number(low_high[0])
                or not _is_number(low_high[1])
            ):
                return fail(
                    "joint_range_missing",
                    f"joint {position} is {kind} and needs range=(low, high)",
                )
            if low_high[0] >= low_high[1]:
                return fail(
                    "joint_range_inverted",
                    f"joint {position} range low must be below high",
                )
        if kind in ENDLESS_KINDS and joint.get("range") is not None:
            motion = "turns without end" if kind == "continuous" else "moves freely"
            return fail(
                "joint_range_forbidden",
                f"joint {position} is {kind} and takes no range: it {motion}",
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
    report = check_sand3d_joint(params.get("joints"))
    report_path = out_dir / "sand3d_joint_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_sand3d_joint_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.sand3d_joint_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "joints": {"type": "array"},
                },
                "required": ["joints"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "sand3d joint gate: four joint kinds (revolute, "
                "prismatic, continuous, free); ranged kinds need a "
                "(low, high) range, endless kinds take none; every "
                "joint names its child, mount, kind, and axis."
            ),
        )
    )
    return ["qa.sand3d_joint_gate"]


__all__ = [
    "ENDLESS_KINDS",
    "JOINT_KINDS",
    "RANGED_KINDS",
    "check_sand3d_joint",
    "register_sand3d_joint_gate_capabilities_once",
]
