"""Programmatic CAD modeling vocabulary gate (``qa.sand3d_modeling_vocabulary_gate``).

A sand3d-style program is a flat list of verbs: profiles build
2D shapes, solids turn them into bodies, edits reshape them,
frames place them, parts add gear/knurl/thread detail, joints
articulate them, and assembly groups and exports them. There
are no category verbs: no ``chair()``, no ``washing_machine()``.
Every verb must come from the closed vocabulary below, the
program must declare its units (millimetres by default, metres
on export), and edge/face selection must use names, never
geometric selectors.

Clean-room restatement of the Sandflow-ai/sand3d method (see
``SAND3D_ATTRIBUTION.md``). Verb names are the public API
surface, restated here as data; no upstream code, program text,
or example material appears in this module. This gate judges
the shape of a program description only; it never runs Blender
or any sand3d code. Real execution needs a separate
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

# Closed verb vocabulary, by family. Restated from the public
# API surface (``s3d.<verb>``); 70 verbs in total.
PROFILES: frozenset[str] = frozenset(
    {
        "rect",
        "circle",
        "ellipse",
        "slot",
        "polygon",
        "poly",
        "arc",
        "tangent_arc",
        "spline",
        "superellipse",
        "station",
        "text",
        "offset",
        "stroke",
        "wrap",
        "mirror",
    }
)
SOLIDS: frozenset[str] = frozenset(
    {
        "extrude",
        "revolve",
        "sweep",
        "loft",
        "body",
        "wire",
        "helix",
        "box",
        "cylinder",
        "tube",
        "cone",
        "sphere",
        "wedge",
        "torus",
        "dome",
    }
)
EDITS: frozenset[str] = frozenset(
    {
        "cut",
        "join",
        "intersect",
        "split",
        "delete",
        "copy",
        "hole",
        "pocket",
        "merge",
        "scale",
        "fillet",
        "chamfer",
        "soften",
        "shell",
        "dent",
    }
)
FRAMES: frozenset[str] = frozenset(
    {
        "Frame",
        "bbox",
        "local",
        "at",
        "transform",
        "grid",
        "ring",
        "along",
        "snap",
    }
)
PARTS: frozenset[str] = frozenset({"gear", "knurl", "thread"})
MATERIALS: frozenset[str] = frozenset({"material"})
ARTICULATION: frozenset[str] = frozenset({"joint", "pose", "seat"})
ASSEMBLY: frozenset[str] = frozenset(
    {
        "group",
        "assembly",
        "attach",
        "Handle",
        "export",
        "empty_scene",
        "units",
        "fingerprint",
    }
)
VOCABULARY: frozenset[str] = (
    PROFILES | SOLIDS | EDITS | FRAMES | PARTS | MATERIALS | ARTICULATION | ASSEMBLY
)
SHAPE_VERBS: frozenset[str] = PROFILES | SOLIDS


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_sand3d_modeling_vocabulary(program: Any) -> dict[str, Any]:
    """Validate a sand3d-style program description.

    Verdicts are ``pass`` / ``fail`` only. The program fails
    when it is not an object, when its verb list is empty or
    not a list of strings, when any verb is outside the closed
    70-verb vocabulary (category verbs such as ``chair`` fail
    here), when no profile or solid verb builds any shape, when
    its units are undeclared, or when it selects edges or faces
    with a geometric selector instead of a name.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(program, dict):
        return fail("program_not_object", "program must be a JSON object")
    verbs = program.get("verbs")
    if not isinstance(verbs, list) or not verbs:
        return fail("verbs_missing", "program must carry a non-empty verb list")
    for verb in verbs:
        if not isinstance(verb, str) or not verb:
            return fail("verb_not_string", "every verb must be a non-empty string")
        if verb not in VOCABULARY:
            return fail(
                "unknown_verb",
                f"verb {verb!r} is outside the closed vocabulary; "
                "there are no category verbs such as chair()",
            )
    if not any(verb in SHAPE_VERBS for verb in verbs):
        return fail(
            "no_shape_verb",
            "program builds no shape: it needs at least one profile or solid verb",
        )
    units = program.get("units")
    if not isinstance(units, str) or not units:
        return fail(
            "units_missing",
            "program must declare its units (millimetres by default)",
        )
    if program.get("uses_geometric_selector") is True:
        return fail(
            "geometric_selector_banned",
            "edge and face selection must use names, never geometric selectors",
        )
    if program.get("selects_edges_or_faces") is True and not program.get("uses_named_selection"):
        return fail(
            "unnamed_selection",
            "edge or face selection without a named selection is not allowed",
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
    report = check_sand3d_modeling_vocabulary(params.get("program"))
    report_path = out_dir / "sand3d_modeling_vocabulary_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_sand3d_modeling_vocabulary_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.sand3d_modeling_vocabulary_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "program": {"type": "object"},
                },
                "required": ["program"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "sand3d modeling vocabulary gate: flat s3d.<verb> "
                "surface, closed 70-verb vocabulary, no category "
                "verbs, units declared, named edge/face selection only."
            ),
        )
    )
    return ["qa.sand3d_modeling_vocabulary_gate"]


__all__ = [
    "EDITS",
    "FRAMES",
    "PARTS",
    "PROFILES",
    "SOLIDS",
    "VOCABULARY",
    "check_sand3d_modeling_vocabulary",
    "register_sand3d_modeling_vocabulary_gate_capabilities_once",
]
