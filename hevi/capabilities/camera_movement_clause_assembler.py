"""Camera movement clause assembler, fake layer
(``video.camera_movement_clause_assembler``).

Contract-only assembler. Given one movement id and a separate scene
clause, it assembles the camera clause from the single-source
four-field entry (Movement / Speed / Framing / End) and keeps the
scene clause separate, so the two can be iterated independently:
the camera clause is the only place a movement may be named, and a
scene clause naming a second movement is rejected under the
one-shot-one-movement rule. This module executes nothing:
``executed_here`` is always false, no video is generated, and no
rendering engine is probed or invoked. Real generation is a
separate case. No site prompt text is copied here. See
CAMERA_MOVEMENTS_ATTRIBUTION.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.cinematic_techniques import (
    detect_movements_in_text,
    get_movement,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False


def assemble_camera_clause(
    movement_id: str,
    scene_clause: str = "",
    subject: str = "",
) -> dict[str, Any]:
    """Assemble a camera clause plus a separate scene clause.

    Raises :class:`CapabilityError` on an unknown movement id or on
    a scene clause that names a camera movement (a second movement
    in the same shot). The returned contract always carries
    ``executed_here: false``: nothing is rendered here.
    """
    if not isinstance(movement_id, str) or not movement_id.strip():
        raise CapabilityError("camera clause assembler: movement_id is required")
    movement_id = movement_id.strip()
    entry = get_movement(movement_id)
    scene = str(scene_clause or "").strip()
    if scene:
        extra = [m for m in detect_movements_in_text(scene) if m != movement_id]
        if extra:
            raise CapabilityError(
                "one-movement check: scene clause must not name a camera "
                f"movement, found {extra}; keep the movement in the "
                "camera clause only"
            )
    camera_clause = (
        f"Camera movement: {entry['movement']} "
        f"Speed: {entry['speed']} Framing: {entry['framing']} "
        f"End: {entry['end']}"
    )
    parts = [camera_clause]
    if subject.strip():
        parts.append(f"Subject: {subject.strip()}.")
    if scene:
        parts.append(scene)
    return {
        "movement_id": movement_id,
        "movement": dict(entry),
        "camera_clause": camera_clause,
        "scene_clause": scene,
        "subject": subject.strip(),
        "prompt": " ".join(parts),
        "executed_here": False,
        "verified_by_hevi_render": False,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = assemble_camera_clause(
        str(params.get("movement", "")),
        str(params.get("scene_clause", "")),
        str(params.get("subject", "")),
    )
    contract_path = out_dir / "camera_movement_clause.json"
    contract_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={"report_json": str(contract_path), "executed_here": False},
    )


def register_camera_movement_clause_assembler_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.camera_movement_clause_assembler",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "movement": {"type": "string"},
                    "scene_clause": {"type": "string"},
                    "subject": {"type": "string"},
                },
                "required": ["movement"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="obase",
            description=(
                "Camera movement clause assembler, fake layer: "
                "assembles the four-field camera clause for one "
                "movement and keeps the scene clause separate; a "
                "scene clause naming a second movement is rejected. "
                "Executed_here is always false; nothing is rendered."
            ),
        )
    )
    return ["video.camera_movement_clause_assembler"]


__all__ = [
    "assemble_camera_clause",
    "register_camera_movement_clause_assembler_capabilities_once",
]
