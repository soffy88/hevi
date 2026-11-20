"""Portrait reference schema (``video.pose_portrait_reference_schema``).

Contract-only schema for one pose-gallery portrait
reference: its id, mode, hair length, hairstyle, gallery
path, and the non-commercial declaration with the CC0
tension acknowledged. Clean-room restatement of the
anhao/ai-pose-gallery-zh portrait library method (see
``AI_POSE_GALLERY_ZH_ATTRIBUTION.md``); no upstream code,
image, or data appears in this schema.

This module is a **contract layer only**. The schema never
renders, scores, or calls a model; ``compile`` returns a
contract declaring ``executed_here: false`` and
``output_file: None`` on a well-formed reference, and raises
``CapabilityError`` on any shape violation. The portrait
CC0 tension is unresolved upstream, so every contract must
carry the acknowledgment; without it compilation fails.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.pose_portrait_library_gate import check_pose_portrait
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
        "reference_id": {"type": "string", "minLength": 1},
        "portrait_id": {"type": "string", "minLength": 1},
        "mode": {"type": "string"},
        "hair_length": {"type": "string"},
        "hairstyle": {"type": "string"},
        "gallery_path": {"type": "string"},
        "commercial_use": {"type": "boolean"},
        "cc0_tension_acknowledged": {"type": "boolean"},
        "real_person_use": {"type": "boolean"},
        "minor_use": {"type": "boolean"},
        "counts": {"type": "object"},
    },
    "required": ["reference_id", "portrait_id", "mode", "hair_length"],
    "additionalProperties": False,
}


def _relative_gallery_path(path: Any) -> str | None:
    if not isinstance(path, str) or not path.strip():
        return None
    if path.startswith("/") or ".." in Path(path).parts:
        return None
    return path


def compile_pose_portrait_reference(reference: Any) -> dict[str, Any]:
    """Compile one portrait reference contract.

    Returns a contract declaring ``executed_here: false``
    and ``output_file: None`` on a well-formed reference.
    Raises :class:`CapabilityError` on any shape violation.
    The contract certifies the shape of the reference only;
    it resolves no file and generates nothing.
    """
    if not isinstance(reference, dict):
        raise CapabilityError("pose_portrait_reference: reference must be a JSON object")
    for key in SCHEMA["required"]:
        if key not in reference:
            raise CapabilityError(f"pose_portrait_reference: missing required field {key!r}")
    extra = sorted(set(reference) - set(SCHEMA["properties"]))
    if extra:
        raise CapabilityError("pose_portrait_reference: unknown fields: " + ", ".join(extra))
    gallery_path = reference.get("gallery_path")
    if gallery_path is not None and _relative_gallery_path(gallery_path) is None:
        raise CapabilityError(
            "pose_portrait_reference: gallery_path must be a relative path "
            "under HEVI_POSE_GALLERY_HOME, never absolute and never with '..'"
        )
    verdict = check_pose_portrait(reference)
    if verdict["verdict"] != "pass":
        first = verdict["issues"][0]
        raise CapabilityError(f"pose_portrait_reference: {first['code']}: {first['detail']}")
    return {
        "contract": "pose-portrait-reference",
        "reference_id": reference["reference_id"],
        "portrait_id": reference["portrait_id"],
        "mode": reference["mode"],
        "gallery_path": gallery_path,
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_pose_portrait_reference(params.get("reference"))
    contract_path = out_dir / "pose_portrait_reference_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={
            "report_json": str(contract_path),
            "reference_id": contract["reference_id"],
            "executed_here": False,
        },
    )


def register_pose_portrait_reference_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.pose_portrait_reference_schema",
            kind="video",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "reference": {"type": "object"},
                },
                "required": ["reference"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="obase",
            line="video",
            description=(
                "Pose-gallery portrait reference contract (fake): "
                "mode, hair length, hairstyle, external gallery "
                "path, CC0 tension acknowledged, non-commercial; "
                "shape only, never executed here."
            ),
        )
    )
    return ["video.pose_portrait_reference_schema"]


__all__ = [
    "SCHEMA",
    "compile_pose_portrait_reference",
    "register_pose_portrait_reference_schema_capabilities_once",
]
