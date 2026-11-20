"""Studio workbench contract schema (``video.pose_studio_workbench_schema``).

Contract-only schema for one pose-gallery Studio workbench
session: its id, the generation protocols selected, the
three reference slots, background generation, and the
IndexedDB history store. Clean-room restatement of the
anhao/ai-pose-gallery-zh workbench method (three core slots
— portrait, costume, pose, with the pose slot's white/depth
switch — plus arbitrary extra reference images, a
three-in-one 1800x1200 canvas composite, cross-page
background generation, IndexedDB history). See
``AI_POSE_GALLERY_ZH_ATTRIBUTION.md``; no upstream code,
image, or data appears in this schema.

This module is a **contract layer only**. The schema never
renders, scores, or calls a model; ``compile`` returns a
contract declaring ``executed_here: false`` and
``output_file: None`` on a well-formed session, and raises
``CapabilityError`` on any shape violation. Keys are always
user-supplied; the workbench contract never carries one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.pose_model_select_gate import PROTOCOLS
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "workbench_id": {"type": "string", "minLength": 1},
        "protocols": {"type": "array"},
        "slots": {"type": "object"},
        "background_generation": {"type": "boolean"},
        "history_store": {"type": "string"},
        "extra_references": {"type": "array"},
        "canvas_size": {"type": "array"},
    },
    "required": ["workbench_id", "protocols", "slots", "history_store"],
    "additionalProperties": False,
}

SLOT_NAMES: frozenset[str] = frozenset({"portrait", "costume", "pose"})


def compile_pose_studio_workbench(session: Any) -> dict[str, Any]:
    """Compile one Studio workbench session contract.

    Returns a contract declaring ``executed_here: false``
    and ``output_file: None`` on a well-formed session.
    Raises :class:`CapabilityError` on any shape violation.
    The contract certifies the shape of the session only;
    it generates nothing and stores nothing.
    """
    if not isinstance(session, dict):
        raise CapabilityError("pose_studio_workbench: session must be a JSON object")
    for key in SCHEMA["required"]:
        if key not in session:
            raise CapabilityError(f"pose_studio_workbench: missing required field {key!r}")
    extra = sorted(set(session) - set(SCHEMA["properties"]))
    if extra:
        raise CapabilityError("pose_studio_workbench: unknown fields: " + ", ".join(extra))
    protocols = session["protocols"]
    if not isinstance(protocols, list) or not protocols:
        raise CapabilityError("pose_studio_workbench: protocols must be a non-empty list")
    unknown = sorted(set(protocols) - PROTOCOLS)
    if unknown:
        raise CapabilityError("pose_studio_workbench: unknown protocols: " + ", ".join(unknown))
    slots = session["slots"]
    if not isinstance(slots, dict):
        raise CapabilityError("pose_studio_workbench: slots must be an object")
    unknown_slots = sorted(set(slots) - SLOT_NAMES)
    if unknown_slots:
        raise CapabilityError("pose_studio_workbench: unknown slots: " + ", ".join(unknown_slots))
    if session["history_store"] != "indexeddb":
        raise CapabilityError(
            "pose_studio_workbench: history_store must be indexeddb, "
            f"got {session['history_store']!r}"
        )
    if "background_generation" in session and not isinstance(
        session["background_generation"], bool
    ):
        raise CapabilityError("pose_studio_workbench: background_generation must be a boolean")
    extra_refs = session.get("extra_references", [])
    if not isinstance(extra_refs, list):
        raise CapabilityError("pose_studio_workbench: extra_references must be a list when given")
    canvas_size = session.get("canvas_size")
    if canvas_size is not None and (
        not isinstance(canvas_size, list)
        or len(canvas_size) != 2
        or any(not isinstance(v, int) or isinstance(v, bool) or v <= 0 for v in canvas_size)
    ):
        raise CapabilityError(
            "pose_studio_workbench: canvas_size must be [width, height] "
            "of positive integers when given"
        )
    return {
        "contract": "pose-studio-workbench",
        "workbench_id": session["workbench_id"],
        "protocols": sorted(set(protocols)),
        "slots": sorted(slots),
        "background_generation": bool(session.get("background_generation", False)),
        "history_store": "indexeddb",
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_pose_studio_workbench(params.get("session"))
    contract_path = out_dir / "pose_studio_workbench_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={
            "report_json": str(contract_path),
            "workbench_id": contract["workbench_id"],
            "executed_here": False,
        },
    )


def register_pose_studio_workbench_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.pose_studio_workbench_schema",
            kind="video",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "session": {"type": "object"},
                },
                "required": ["session"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="obase",
            line="video",
            description=(
                "Pose-gallery Studio workbench contract (fake): "
                "protocol selection, three reference slots, "
                "background generation, IndexedDB history; shape "
                "only, never executed here."
            ),
        )
    )
    return ["video.pose_studio_workbench_schema"]


__all__ = [
    "SCHEMA",
    "SLOT_NAMES",
    "compile_pose_studio_workbench",
    "register_pose_studio_workbench_schema_capabilities_once",
]
