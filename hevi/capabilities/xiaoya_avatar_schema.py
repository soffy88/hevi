"""Xiaoya avatar schema (``video.xiaoya_avatar_schema``).

Fake-level contract for one Xiaoya host avatar: its avatar
key, its face source, its motion source, its name, and whether
it is the fixed host. The contract certifies the shape of the
plan only. It loads no image or video, holds no key, and
starts nothing: every compiled contract declares
``executed_here: false`` and ``output_file: None``. The banned
name below appears only to be refused; the host is called by
its plain name, never by that one.

Clean-room restatement of the avatar declaration found in the
``live-parity`` branch checkout (see
``DIGITAL_HOST_IMPROVEMENT_ATTRIBUTION.md``).
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

AVATAR_KEYS: frozenset[str] = frozenset({"xiaoya_d", "xiaoya_e", "v1"})
FACE_SOURCES: frozenset[str] = frozenset({"ai_generated", "provided"})
MOTION_SOURCES: frozenset[str] = frozenset({"pexels", "ai_generated"})
BANNED_NAME = "赛博小雅"
_KEY_FIELDS: frozenset[str] = frozenset({"api_key", "key", "token", "secret", "access_key"})


def _find_key_fields(node: Any, path: str, found: list[str]) -> None:
    """Collect paths where key material hides in a plan."""
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}" if path else str(key)
            if key in _KEY_FIELDS and isinstance(value, str) and value.strip():
                found.append(child)
            _find_key_fields(value, child, found)
    elif isinstance(node, list):
        for position, value in enumerate(node):
            _find_key_fields(value, f"{path}[{position}]", found)


def compile_xiaoya_avatar(plan: Any) -> dict[str, Any]:
    """Compile one Xiaoya avatar contract.

    ``plan`` carries ``avatar_key`` (xiaoya_d, xiaoya_e, or
    v1), ``face`` (``source`` ai_generated or provided, plus
    ``confirmed``), ``motion_source`` (pexels or
    ai_generated), ``name`` (a non-empty string), and
    ``fixed_host`` (a boolean). Raises :class:`CapabilityError`
    on any shape violation, on any key material, on a real
    person's photo as the face, on an unconfirmed ``xiaoya_e``
    face, on Pexels motion as the fixed host without a model
    release, or on the banned name. The returned contract
    records that nothing was executed here.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("xiaoya avatar plan must be an object")
    if plan.get("executed_here") is True:
        raise CapabilityError("avatar claims are refused here; this contract loads nothing")
    key_fields: list[str] = []
    _find_key_fields(plan, "", key_fields)
    if key_fields:
        raise CapabilityError(
            f"keys never enter the contract; key material refused at {key_fields[0]}"
        )
    avatar_key = plan.get("avatar_key")
    if avatar_key not in AVATAR_KEYS:
        raise CapabilityError("avatar_key must be xiaoya_d, xiaoya_e, or v1")
    face = plan.get("face")
    if not isinstance(face, dict):
        raise CapabilityError("xiaoya avatar plan requires a face object")
    face_source = face.get("source")
    if face_source == "real_person_photo":
        raise CapabilityError("a real person's photo is never a host face")
    if face_source not in FACE_SOURCES:
        raise CapabilityError("face source must be ai_generated or provided")
    if avatar_key == "xiaoya_e" and face.get("confirmed") is not True:
        raise CapabilityError("the xiaoya_e face source must be confirmed before it is used")
    motion_source = plan.get("motion_source")
    if motion_source not in MOTION_SOURCES:
        raise CapabilityError("motion_source must be pexels or ai_generated")
    fixed_host = plan.get("fixed_host")
    if not isinstance(fixed_host, bool):
        raise CapabilityError("fixed_host must be a boolean")
    if motion_source == "pexels" and fixed_host and plan.get("model_release") is not True:
        raise CapabilityError(
            "Pexels motion carries no model release: not the fixed host's motion source"
        )
    name = plan.get("name")
    if not isinstance(name, str) or not name.strip():
        raise CapabilityError("the host needs a non-empty name")
    if name == BANNED_NAME:
        raise CapabilityError("that host name is not revived here")
    return {
        "contract": "xiaoya-avatar",
        "avatar_key": avatar_key,
        "face_source": face_source,
        "motion_source": motion_source,
        "name": name,
        "fixed_host": fixed_host,
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_xiaoya_avatar(params.get("plan"))
    contract_path = out_dir / "xiaoya_avatar_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={
            "report_json": str(contract_path),
            "avatar_key": contract["avatar_key"],
            "executed_here": False,
        },
    )


def register_xiaoya_avatar_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.xiaoya_avatar_schema",
            kind="video",
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
            line="video",
            description=(
                "xiaoya avatar contract (fake): avatar key, face "
                "source, motion source, name, fixed-host flag; "
                "shape only, never executed here."
            ),
        )
    )
    return ["video.xiaoya_avatar_schema"]


__all__ = [
    "AVATAR_KEYS",
    "BANNED_NAME",
    "FACE_SOURCES",
    "MOTION_SOURCES",
    "compile_xiaoya_avatar",
    "register_xiaoya_avatar_schema_capabilities_once",
]
