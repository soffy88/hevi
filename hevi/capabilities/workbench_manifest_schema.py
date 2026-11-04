"""Workbench manifest schema (``video.workbench_manifest_schema``).

Contract-only schema for a browser workbench manifest: the shape
of the manifest, the three editability tiers, and the parity
verdict vocabulary. Tier one edits time and layer (start, length,
uniform speed, trim-in, opacity, scale, offset, track swap,
hide). Tier two edits content and style, but only through
parameters a component exposes with defaults plus a schema.
Tier three imports a shot, transition, caption, or effect as one
decomposed segment. Rhythm-defining constants are never part of
the schema. Parity compares imported and original frames pixel by
pixel; a difference below one tenth of a percent counts as a
match, and the run reports one of three exit states (match,
mismatch, or comparison unavailable). This module builds no
editor and runs no parity check: ``executed_here`` is always
false and ``output_file`` is always null. See
VIDEO_SHOTCRAFT_ATTRIBUTION.md.
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
from hevi.capabilities.workbench_manifest_gate import MANIFEST_SECTIONS

_Registered = False

# Tier-one time/layer fields. Speed is a uniform remap only.
TIME_LAYER_FIELDS: tuple[str, ...] = (
    "start",
    "duration",
    "speed",
    "trim_in",
    "opacity",
    "scale",
    "offset",
    "track",
    "hidden",
)

# Admitted schema field types for tier-two parameters.
SCHEMA_FIELD_TYPES: tuple[str, ...] = (
    "text",
    "color",
    "number",
    "position",
    "boolean",
    "enum",
)

# Uniform speed bounds for tier-one remap.
SPEED_MIN = 0.25
SPEED_MAX = 4.0

# Parity verdict vocabulary: match, mismatch, unavailable.
PARITY_EXIT_CODES: tuple[int, ...] = (0, 1, 2)

# Pixel-difference share below which parity counts as a match.
PARITY_MATCH_THRESHOLD = 0.001


def _fail(message: str) -> None:
    raise CapabilityError(message)


def _check_manifest(manifest: Any) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        _fail("workbench manifest must be a JSON object")
    version = manifest.get("manifest_version")
    if not isinstance(version, str) or not version.strip():
        _fail("manifest version must be a pinned non-empty string")
    if manifest.get("timeline_same_source") is not True:
        _fail("manifest timeline must come from the same source as the main composition")
    sections = manifest.get("sections")
    if not isinstance(sections, list):
        _fail("manifest must declare a sections list")
    unknown = [s for s in sections if s not in MANIFEST_SECTIONS]
    if unknown:
        _fail(f"sections outside the closed vocabulary: {unknown}")
    if manifest.get("rhythm_constants_exposed") is True:
        _fail("rhythm-defining constants must never enter the schema")
    tiers = manifest.get("tiers")
    if tiers is not None:
        if not isinstance(tiers, dict):
            _fail("tiers must be an object when present")
        time_layer = tiers.get("time_layer", {})
        if not isinstance(time_layer, dict):
            _fail("time_layer tier must be an object")
        bad_fields = [f for f in time_layer if f not in TIME_LAYER_FIELDS]
        if bad_fields:
            _fail(f"time/layer fields outside the schema: {bad_fields}")
        speed = time_layer.get("speed")
        if speed is not None:
            if not isinstance(speed, (int, float)) or isinstance(speed, bool):
                _fail("speed must be a number")
            if speed < SPEED_MIN or speed > SPEED_MAX:
                _fail("speed must sit within the uniform remap bounds")
        content_style = tiers.get("content_style", {})
        if not isinstance(content_style, dict):
            _fail("content_style tier must be an object")
        for name, field in content_style.items():
            if not isinstance(field, dict):
                _fail(f"content/style parameter {name!r} must be an object")
            if field.get("type") not in SCHEMA_FIELD_TYPES:
                _fail(f"content/style parameter {name!r} has an unknown schema type")
            if "default" not in field:
                _fail(f"content/style parameter {name!r} must carry a default")
    return {
        "manifest_version": version,
        "sections": list(sections),
        "time_layer_fields": list(TIME_LAYER_FIELDS),
        "schema_field_types": list(SCHEMA_FIELD_TYPES),
        "speed_bounds": [SPEED_MIN, SPEED_MAX],
        "rhythm_constants_exposed": False,
        "parity_exit_codes": list(PARITY_EXIT_CODES),
        "parity_match_threshold": PARITY_MATCH_THRESHOLD,
    }


def compile_workbench_manifest_contract(request: Any = None) -> dict[str, Any]:
    """Compile a workbench manifest contract from a manifest object.

    ``request`` may be null (schema shape only) or an object with a
    ``manifest``. Shape violations raise :class:`CapabilityError`.
    Nothing is built or compared here.
    """
    if request is None:
        checked = {
            "manifest_version": None,
            "sections": list(MANIFEST_SECTIONS),
            "time_layer_fields": list(TIME_LAYER_FIELDS),
            "schema_field_types": list(SCHEMA_FIELD_TYPES),
            "speed_bounds": [SPEED_MIN, SPEED_MAX],
            "rhythm_constants_exposed": False,
            "parity_exit_codes": list(PARITY_EXIT_CODES),
            "parity_match_threshold": PARITY_MATCH_THRESHOLD,
        }
    elif isinstance(request, dict):
        checked = _check_manifest(request.get("manifest"))
    else:
        _fail("workbench manifest request must be a JSON object or null")
    return {
        "manifest": checked,
        "parity_verified": False,
        "parity_run": False,
        "editor_built_here": False,
        "executed_here": False,
        "rendered_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_workbench_manifest_contract(params.get("request"))
    contract_path = out_dir / "workbench_manifest_schema.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={"contract_json": str(contract_path), "executed_here": False},
    )


def register_workbench_manifest_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.workbench_manifest_schema",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "request": {"type": ["object", "null"]},
                },
                "required": [],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="obase",
            description=(
                "Workbench manifest schema (contract only): manifest "
                "shape, three editability tiers, and the parity "
                "verdict vocabulary; no editor is built and no "
                "parity run happens here."
            ),
        )
    )
    return ["video.workbench_manifest_schema"]


__all__ = [
    "PARITY_EXIT_CODES",
    "PARITY_MATCH_THRESHOLD",
    "SCHEMA_FIELD_TYPES",
    "SPEED_MAX",
    "SPEED_MIN",
    "TIME_LAYER_FIELDS",
    "compile_workbench_manifest_contract",
    "register_workbench_manifest_schema_capabilities_once",
]
