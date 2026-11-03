"""Smart reference resolution (``pipeline.smart_reference``).

Prompts name pictures in words -- "图1", "图片2", "图 1" -- and those
words have to mean a specific connected asset, or nothing at all.
This module parses those references against the assets actually
connected to the project:

* Pattern: ``图片`` / ``圖片`` / ``图像`` / ``图`` / ``圖`` followed
  by optional whitespace and a number (``图1``, ``图片2``, ``图 1``).
  The longer forms are tried first so ``图片2`` parses as one
  reference to picture 2, not as ``图`` plus a stray character.
* Connected materials are supplied by the caller as a list of
  objects, each naming its picture number (``picture_number`` or
  ``index``) and its asset (``asset_id`` and/or ``path``). The
  module never invents an asset: the mapping table is built only
  from that list.
* Resolution is strict:
  - exactly one candidate for a number -> ``resolved``;
  - no candidate (the picture was never connected) -> ``skipped``
    with reason ``unconnected``;
  - more than one candidate for the same number (duplicate
    connections) -> ``skipped`` with reason ``ambiguous``.
  A skipped reference is recorded as skipped in the mapping table;
  it is never guessed, never hard-coded to a "best" asset, and the
  original prompt text is left untouched for skipped references.
* The mapping table is written into the project graph
  (``graph["references"]``) and into the project manifest
  (``manifest["references"]``) by ``apply_references`` so the
  resolution is auditable from either place.
"""

from __future__ import annotations

import copy
import json
import re
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

_REFERENCE_RE = re.compile(r"(?:图片|圖片|图像|圖|图)\s*(\d+)")


def _fail(message: str) -> None:
    raise CapabilityError(f"pipeline.smart_reference: {message}")


def _material_number(material: dict[str, Any]) -> int | None:
    for key in ("picture_number", "index", "number"):
        value = material.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
    return None


def _candidates_by_number(materials: Any) -> dict[int, list[dict[str, Any]]]:
    if not isinstance(materials, list):
        _fail("materials must be a list of connected assets")
    by_number: dict[int, list[dict[str, Any]]] = {}
    for material in materials:
        if not isinstance(material, dict):
            _fail(f"material is not an object: {material!r}")
        number = _material_number(material)
        if number is None:
            _fail(
                f"material has no picture_number/index/number: {material!r}"
            )
        by_number.setdefault(number, []).append(material)
    return by_number


def parse_references(
    prompt: str, materials: Any
) -> dict[str, Any]:
    """Parse picture references in ``prompt`` against ``materials``."""
    if not isinstance(prompt, str):
        _fail("prompt must be a string")
    by_number = _candidates_by_number(materials)
    mapping: list[dict[str, Any]] = []
    for match in _REFERENCE_RE.finditer(prompt):
        raw = match.group(0)
        number = int(match.group(1))
        candidates = by_number.get(number, [])
        if len(candidates) == 1:
            candidate = candidates[0]
            mapping.append({
                "raw": raw,
                "number": number,
                "status": "resolved",
                "asset_id": candidate.get("asset_id"),
                "path": candidate.get("path"),
                "reason": "",
            })
        elif not candidates:
            mapping.append({
                "raw": raw,
                "number": number,
                "status": "skipped",
                "asset_id": None,
                "path": None,
                "reason": (
                    f"unconnected: no connected asset for picture {number}; "
                    "reference skipped, not guessed"
                ),
            })
        else:
            mapping.append({
                "raw": raw,
                "number": number,
                "status": "skipped",
                "asset_id": None,
                "path": None,
                "reason": (
                    f"ambiguous: {len(candidates)} connected assets claim "
                    f"picture {number}; reference skipped, not guessed"
                ),
            })
    return {
        "prompt": prompt,
        "references": mapping,
        "resolved_count": sum(1 for r in mapping if r["status"] == "resolved"),
        "skipped_count": sum(1 for r in mapping if r["status"] == "skipped"),
        "skipped": [r for r in mapping if r["status"] == "skipped"],
    }


def apply_references_to_graph(
    graph: dict[str, Any], prompt: str, materials: Any
) -> dict[str, Any]:
    """Return a copy of ``graph`` carrying the reference mapping table."""
    if not isinstance(graph, dict) or "nodes" not in graph:
        _fail("apply_references_to_graph: graph has no nodes list")
    parsed = parse_references(prompt, materials)
    new_graph = copy.deepcopy(graph)
    new_graph["references"] = parsed["references"]
    new_graph["reference_summary"] = {
        "resolved_count": parsed["resolved_count"],
        "skipped_count": parsed["skipped_count"],
    }
    return new_graph


def attach_references_to_manifest(
    project_root: Path, references: list[dict[str, Any]]
) -> dict[str, Any]:
    """Store a reference mapping table in a project manifest."""
    root = Path(project_root)
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        _fail(
            f"manifest not found: {manifest_path} "
            "(run pipeline.project_handoff create first)"
        )
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _fail(f"manifest is not valid JSON: {manifest_path}")
    if not isinstance(references, list):
        _fail("references must be a list (the mapping table)")
    data["references"] = copy.deepcopy(references)
    manifest_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return data


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
             aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    action = params.get("action", "parse")
    if action == "parse":
        result: dict[str, Any] = {
            "capability": "pipeline.smart_reference",
            **parse_references(
                str(params.get("prompt", "")),
                params.get("materials", []),
            ),
        }
    elif action == "apply":
        graph = apply_references_to_graph(
            dict(params.get("graph", {})),
            str(params.get("prompt", "")),
            params.get("materials", []),
        )
        result = {"capability": "pipeline.smart_reference", "graph": graph}
    else:
        _fail(f"unknown action {action!r}; known: parse, apply")
    report_path = out_dir / "smart_reference_report.json"
    report_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "result": result},
    )


def register_smart_reference_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="pipeline.smart_reference",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["parse", "apply"]},
                    "prompt": {"type": "string"},
                    "materials": {"type": "array",
                                  "items": {"type": "object"}},
                    "graph": {"type": "object"},
                },
                "required": [],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Smart reference resolution: prompt references such as "
                "图1 / 图片2 / 图 1 are parsed against actually connected "
                "assets; exactly one candidate resolves, while ambiguous "
                "or unconnected references are recorded as skipped, "
                "never guessed or hard-coded. The mapping table is "
                "written into the project graph and manifest."
            ),
            line="pipeline",
        )
    )
    return ["pipeline.smart_reference"]


register_smart_reference_capabilities_once()
