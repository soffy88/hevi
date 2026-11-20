"""Costume reference schema (``video.pose_costume_reference_schema``).

Contract-only schema for one pose-gallery costume
reference: its id, source, category, set, tags, gallery
path, and the non-commercial declaration. Clean-room
restatement of the anhao/ai-pose-gallery-zh costume library
method (see ``AI_POSE_GALLERY_ZH_ATTRIBUTION.md``); no
upstream code, image, or data appears in this schema.

This module is a **contract layer only**. The schema never
renders, scores, or calls a model; ``compile`` returns a
contract declaring ``executed_here: false`` and
``output_file: None`` on a well-formed reference, and raises
``CapabilityError`` on any shape violation. Gallery paths
are relative paths under ``HEVI_POSE_GALLERY_HOME``; an
absolute path or a ``..`` traversal is refused.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.pose_costume_library_gate import check_pose_costume
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
        "source": {"type": "string"},
        "category": {"type": "string"},
        "set_id": {"type": "string", "minLength": 1},
        "tags": {"type": "array"},
        "gallery_path": {"type": "string"},
        "dynasty": {"type": "string"},
        "hotlink": {"type": "boolean"},
        "offline_available": {"type": "boolean"},
        "no_redistribution": {"type": "boolean"},
        "no_real_person_or_minor": {"type": "boolean"},
        "commercial_use": {"type": "boolean"},
        "images_bundled": {"type": "boolean"},
        "total_sets": {"type": "number"},
        "category_sets": {"type": "number"},
    },
    "required": ["reference_id", "source", "set_id"],
    "additionalProperties": False,
}


def _relative_gallery_path(path: Any) -> str | None:
    if not isinstance(path, str) or not path.strip():
        return None
    if path.startswith("/") or ".." in Path(path).parts:
        return None
    return path


def compile_pose_costume_reference(reference: Any) -> dict[str, Any]:
    """Compile one costume reference contract.

    Returns a contract declaring ``executed_here: false``
    and ``output_file: None`` on a well-formed reference.
    Raises :class:`CapabilityError` on any shape violation.
    The contract certifies the shape of the reference only;
    it resolves no file and generates nothing.
    """
    if not isinstance(reference, dict):
        raise CapabilityError("pose_costume_reference: reference must be a JSON object")
    for key in SCHEMA["required"]:
        if key not in reference:
            raise CapabilityError(f"pose_costume_reference: missing required field {key!r}")
    extra = sorted(set(reference) - set(SCHEMA["properties"]))
    if extra:
        raise CapabilityError("pose_costume_reference: unknown fields: " + ", ".join(extra))
    gallery_path = reference.get("gallery_path")
    if gallery_path is not None and _relative_gallery_path(gallery_path) is None:
        raise CapabilityError(
            "pose_costume_reference: gallery_path must be a relative path "
            "under HEVI_POSE_GALLERY_HOME, never absolute and never with '..'"
        )
    verdict = check_pose_costume(reference)
    if verdict["verdict"] != "pass":
        first = verdict["issues"][0]
        raise CapabilityError(f"pose_costume_reference: {first['code']}: {first['detail']}")
    return {
        "contract": "pose-costume-reference",
        "reference_id": reference["reference_id"],
        "source": reference["source"],
        "set_id": reference["set_id"],
        "gallery_path": gallery_path,
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_pose_costume_reference(params.get("reference"))
    contract_path = out_dir / "pose_costume_reference_contract.json"
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


def register_pose_costume_reference_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.pose_costume_reference_schema",
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
                "Pose-gallery costume reference contract (fake): "
                "source, category, set, tags, external gallery path, "
                "non-commercial declaration; shape only, never "
                "executed here."
            ),
        )
    )
    return ["video.pose_costume_reference_schema"]


__all__ = [
    "SCHEMA",
    "compile_pose_costume_reference",
    "register_pose_costume_reference_schema_capabilities_once",
]
