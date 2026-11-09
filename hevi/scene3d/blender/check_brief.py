"""Compare a measured Blender scene with the brief's hard numbers.

Only measured values count; the brief is never echoed back as evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = ["check_brief", "load_and_check"]


def check_brief(brief: dict[str, Any], measured: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    want_res = [int(brief["width"]), int(brief["height"])]
    if list(measured.get("resolution") or []) != want_res:
        errors.append(f"resolution {measured.get('resolution')} != {want_res}")
    if int(measured.get("fps") or 0) != int(brief["fps"]):
        errors.append(f"fps {measured.get('fps')} != {brief['fps']}")
    if abs(float(measured.get("duration_s") or 0) - float(brief["duration_s"])) > 0.11:
        errors.append(f"duration {measured.get('duration_s')}s != {brief['duration_s']}s")

    tris = int(measured.get("triangles") or 0)
    budget = int(brief.get("max_triangles") or 10**12)
    if tris > budget:
        errors.append(f"triangles {tris} > budget {budget}")
    if tris > 0.8 * budget:
        warnings.append(f"triangles near budget ({tris}/{budget})")

    size = measured.get("bbox_size_m") or [0, 0, 0]
    limit = brief.get("max_bbox_m") or [10**9] * 3
    for axis, (got, cap) in enumerate(zip(size, limit, strict=False)):
        if float(got) > float(cap):
            errors.append(f"bbox axis {axis} {got}m > {cap}m")

    allowed = tuple(brief.get("allow_non_manifold_prefixes") or [])
    for name, count in (measured.get("non_manifold") or {}).items():
        if not allowed or not str(name).startswith(allowed):
            errors.append(f"non-manifold {count} edges on {name}")

    suffix = brief.get("forbid_suffix", ".001")
    dupes = measured.get("duplicate_suffix_objects") or []
    if suffix and dupes:
        errors.append(f"duplicate-suffix objects (residual duplicates): {dupes}")
    if measured.get("zero_area_objects"):
        errors.append(f"zero-area faces: {measured['zero_area_objects']}")
    if measured.get("no_material_objects"):
        errors.append(f"mesh objects without material: {measured['no_material_objects']}")
    if not measured.get("mesh_objects"):
        errors.append("scene has no mesh objects")
    if measured.get("origin") and brief.get("require_origin_at_zero"):
        origin = measured["origin"]
        if any(abs(float(v)) > 0.01 for v in origin):
            errors.append(f"scene origin {origin} is not at zero")
    if measured.get("residual_objects"):
        errors.append(f"residual objects: {measured['residual_objects']}")
    if brief.get("require_angles") and not measured.get("angles"):
        errors.append("multi-angle stills were required but none were rendered")

    return {
        "verdict": "pass" if not errors else "fail",
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "measured": {
            key: measured.get(key)
            for key in (
                "resolution", "fps", "duration_s", "triangles", "bbox_size_m",
                "origin", "mesh_objects", "angles",
            )
        },
    }


def load_and_check(brief_path: str | Path, measured_path: str | Path) -> dict[str, Any]:
    brief = json.loads(Path(brief_path).read_text(encoding="utf-8"))
    measured = json.loads(Path(measured_path).read_text(encoding="utf-8"))
    return check_brief(brief, measured)
