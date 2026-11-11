"""Six-format export gate (``qa.sand3d_export_format_gate``).

A sand3d-style export writes exactly one of six formats,
chosen by file suffix: GLB, URDF, USDA, IFC, OBJ, STL. Two
families are refused explicitly, with a redirect instead of
silence: binary/packaged USD (``.usd`` / ``.usdc`` / ``.usdz``)
is written by USD's own library, so the program must write
``.usda`` text and convert it with USD's tools; Revit formats
(``.rvt`` / ``.rfa`` / ``.rte`` / ``.rft``) are written by
Revit alone, so the program must write ``.ifc``. Any other
suffix fails as unsupported. The gate never pretends an
unsupported format is supported.

Clean-room restatement of the Sandflow-ai/sand3d method (see
``SAND3D_ATTRIBUTION.md``); no upstream code appears here.
This gate judges export descriptions only; it never runs
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

SUPPORTED_FORMATS: frozenset[str] = frozenset({".glb", ".urdf", ".usda", ".ifc", ".obj", ".stl"})
USD_REJECTED: frozenset[str] = frozenset({".usd", ".usdc", ".usdz"})
REVIT_REJECTED: frozenset[str] = frozenset({".rvt", ".rfa", ".rte", ".rft"})


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _suffix(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].lower()


def check_sand3d_export_format(exports: Any) -> dict[str, Any]:
    """Validate a sand3d-style export list.

    Verdicts are ``pass`` / ``fail`` only. The list fails when
    it is not a non-empty list, when any entry is not an object
    with a ``path`` string, when a path has no extension, when
    the suffix is a USD binary/packaged format (redirect: write
    ``.usda`` and convert with USD's tools), when the suffix is
    a Revit format (redirect: write ``.ifc``), or when the
    suffix is any other unsupported format.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(exports, list) or not exports:
        return fail("exports_missing", "export list must be a non-empty list")
    for position, entry in enumerate(exports):
        if not isinstance(entry, dict):
            return fail(
                "export_not_object",
                f"export {position} must be an object",
            )
        path = entry.get("path")
        if not isinstance(path, str) or not path:
            return fail(
                "export_path_missing",
                f"export {position} must carry a path string",
            )
        suffix = _suffix(path)
        if not suffix:
            return fail(
                "export_no_extension",
                f"export {position} path {path!r} has no extension",
            )
        if suffix in USD_REJECTED:
            return fail(
                "usd_binary_rejected",
                f"export {position} suffix {suffix} is written by "
                "USD's own library, which sand3d does not take: "
                "write .usda, USD as text, and convert it with "
                "USD's tools",
            )
        if suffix in REVIT_REJECTED:
            return fail(
                "revit_format_rejected",
                f"export {position} suffix {suffix} is Revit's own "
                "format, which Revit alone writes: write .ifc, the "
                "open standard",
            )
        if suffix not in SUPPORTED_FORMATS:
            return fail(
                "unsupported_format",
                f"export {position} suffix {suffix} is not a format "
                "sand3d writes: name the file .glb, .ifc, .obj, "
                ".stl, .urdf or .usda",
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
    report = check_sand3d_export_format(params.get("exports"))
    report_path = out_dir / "sand3d_export_format_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_sand3d_export_format_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.sand3d_export_format_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "exports": {"type": "array"},
                },
                "required": ["exports"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "sand3d export format gate: six formats by suffix "
                "(GLB/URDF/USDA/IFC/OBJ/STL); USD binary and Revit "
                "formats refused explicitly with a redirect, never "
                "silently supported."
            ),
        )
    )
    return ["qa.sand3d_export_format_gate"]


__all__ = [
    "REVIT_REJECTED",
    "SUPPORTED_FORMATS",
    "USD_REJECTED",
    "check_sand3d_export_format",
    "register_sand3d_export_format_gate_capabilities_once",
]
