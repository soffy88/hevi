"""IFC/BIM honesty gate (``qa.sand3d_ifc_honesty_gate``).

An IFC export carries two honest limits that must travel with
the file. First, IFC GlobalIds are unstable: editing or
moving a part can change its ID, and identical parts can
share one, so no ID may be used to track a part across
exports. Second, the export carries no mass, inertia, or
dynamics: masses, frictions, efforts, and drives are outside
what the exporter writes. An IFC export without the
GlobalId notice, or without a declared exclusion list, fails.

Clean-room restatement of the Sandflow-ai/sand3d method (see
``SAND3D_ATTRIBUTION.md``); no upstream code appears here.
This gate judges IFC export descriptions only; it never runs
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

# Quantities the IFC exporter does not write. An export must
# declare at least one of these as excluded.
KNOWN_EXCLUSIONS: frozenset[str] = frozenset(
    {"mass", "inertia", "dynamics", "friction", "effort", "drive"}
)


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_sand3d_ifc_honesty(export: Any) -> dict[str, Any]:
    """Validate a sand3d-style IFC export description.

    Verdicts are ``pass`` / ``fail`` only. The export fails
    when it is not an object, when its format is not ``ifc``,
    when it does not state that GlobalIds are unstable, when
    it carries no GlobalId notice text, or when its exclusion
    list names none of the quantities the exporter does not
    write (mass, inertia, dynamics, friction, effort, drive).
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(export, dict):
        return fail("export_not_object", "IFC export must be a JSON object")
    if export.get("format") != "ifc":
        return fail(
            "format_not_ifc",
            "this gate judges IFC exports only",
        )
    if export.get("states_global_id_unstable") is not True:
        return fail(
            "global_id_stability_unstated",
            "IFC export must state that GlobalIds are unstable "
            "and cannot track parts across exports",
        )
    notice = export.get("global_id_notice")
    if not isinstance(notice, str) or not notice.strip():
        return fail(
            "global_id_notice_missing",
            "IFC export must carry its GlobalId notice text beside the product",
        )
    excluded = export.get("excluded_quantities")
    if not isinstance(excluded, list) or not excluded:
        return fail(
            "excluded_quantities_missing",
            "IFC export must declare the quantities the exporter does not write",
        )
    declared = {str(item).strip().lower() for item in excluded if isinstance(item, str)}
    if not declared & KNOWN_EXCLUSIONS:
        return fail(
            "excluded_quantities_incomplete",
            "exclusion list must name at least one of mass, "
            "inertia, dynamics, friction, effort, drive",
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
    report = check_sand3d_ifc_honesty(params.get("export"))
    report_path = out_dir / "sand3d_ifc_honesty_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_sand3d_ifc_honesty_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.sand3d_ifc_honesty_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "export": {"type": "object"},
                },
                "required": ["export"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "sand3d IFC honesty gate: GlobalId instability must "
                "be stated and carried beside the product; mass, "
                "inertia, and dynamics exclusions must be declared."
            ),
        )
    )
    return ["qa.sand3d_ifc_honesty_gate"]


__all__ = [
    "KNOWN_EXCLUSIONS",
    "check_sand3d_ifc_honesty",
    "register_sand3d_ifc_honesty_gate_capabilities_once",
]
