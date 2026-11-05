"""Code-film generation record schema (``video.codefilm_generation_record_schema``).

Fake-level contract for a code-film generation record of the
kind described in the Infinite Creation delta2 review (see
``INFINITE_CREATION_ATTRIBUTION.md``): a record naming the
style and category, the materials supplied (image, audio,
video, or document), and the record operations performed
against it (query, edit, regenerate, stop, batch delete). The
contract certifies the shape of the record only. It renders
nothing and generates nothing: every compiled contract
declares ``executed_here: false``, and any record claiming a
render here fails outright. Whether a style looks right on
screen is a question for a real rendering run, which is a
separate case.
"""

from __future__ import annotations

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

CATEGORIES = (
    "editing_documentary",
    "evidence_imaging",
    "hand_drawn",
    "east_asian_traditional",
    "print",
    "graphic_typography",
    "information_publishing",
    "cartoon_animation",
    "game",
    "film_era",
    "material_3d",
)
_MATERIAL_KINDS = ("image", "audio", "video", "document")
_OPERATIONS = ("query", "edit", "regenerate", "stop", "batch_delete")

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"video.codefilm_generation_record_schema: {detail}"}
    issue.update(extra)
    return issue


def compile_codefilm_generation_record(record: Any) -> dict[str, Any]:
    """Compile one code-film generation record contract.

    ``record`` carries ``record_id``, ``style_id``, ``category``,
    ``materials`` and ``operations``. Raises
    :class:`CapabilityError` on any shape violation, on a
    ``regenerate`` without a source record, on a ``stop``
    without a target record, on a ``batch_delete`` without a
    scope, or on any claim that rendering happened here. The
    returned contract records that nothing was executed here.
    """
    if not isinstance(record, dict):
        raise CapabilityError("generation record must be an object")
    issues: list[dict[str, Any]] = []
    if not isinstance(record.get("record_id"), str) or not record["record_id"].strip():
        issues.append(_issue("record_id_missing", "generation record requires a record_id"))
    style_id = record.get("style_id")
    if not isinstance(style_id, str) or not _SLUG_RE.match(style_id):
        issues.append(_issue("style_id_invalid", "style_id must be a lowercase slug"))
    if record.get("category") not in CATEGORIES:
        issues.append(_issue("category_invalid", "category must be one of the closed list"))
    materials = record.get("materials")
    if not isinstance(materials, list) or not materials:
        issues.append(
            _issue("materials_missing", "generation record requires a non-empty materials list")
        )
        materials = []
    for position, material in enumerate(materials):
        if not isinstance(material, dict):
            issues.append(_issue("material_not_object", f"material {position} is not an object"))
            continue
        if material.get("kind") not in _MATERIAL_KINDS:
            issues.append(
                _issue(
                    "material_kind_invalid",
                    f"material {position} kind must be one of {_MATERIAL_KINDS}",
                )
            )
        if not isinstance(material.get("ref"), str) or not material["ref"].strip():
            issues.append(_issue("material_ref_missing", f"material {position} requires a ref"))
    operations = record.get("operations")
    if not isinstance(operations, list):
        issues.append(_issue("operations_invalid", "operations must be a list when present"))
        operations = []
    for position, operation in enumerate(operations):
        if not isinstance(operation, dict):
            issues.append(_issue("operation_not_object", f"operation {position} is not an object"))
            continue
        op = operation.get("op")
        if op not in _OPERATIONS:
            issues.append(
                _issue(
                    "operation_invalid",
                    f"operation {position} op must be one of {_OPERATIONS}",
                )
            )
            continue
        if op == "regenerate" and (
            not isinstance(operation.get("source_record_id"), str)
            or not operation["source_record_id"].strip()
        ):
            issues.append(
                _issue(
                    "regenerate_source_missing",
                    f"operation {position} (regenerate) requires source_record_id",
                )
            )
        if op == "stop" and (
            not isinstance(operation.get("target_record_id"), str)
            or not operation["target_record_id"].strip()
        ):
            issues.append(
                _issue(
                    "stop_target_missing",
                    f"operation {position} (stop) requires target_record_id",
                )
            )
        if op == "batch_delete" and (
            not isinstance(operation.get("scope"), str) or not operation["scope"].strip()
        ):
            issues.append(
                _issue(
                    "batch_delete_scope_missing",
                    f"operation {position} (batch_delete) requires a scope",
                )
            )
    if record.get("rendered_here") is not False:
        issues.append(
            _issue(
                "unverified_render_claim",
                "generation record must declare rendered_here false; this contract never renders",
            )
        )
    if record.get("generated_here") is True:
        issues.append(
            _issue(
                "unverified_generation_claim",
                "generation record must not claim generation happened here",
            )
        )
    if issues:
        raise CapabilityError(
            "generation record failed validation: " + "; ".join(issue["detail"] for issue in issues)
        )
    contract = {
        "record_id": record.get("record_id"),
        "style_id": record.get("style_id"),
        "category": record.get("category"),
        "materials": materials,
        "operations": operations,
        "executed_here": False,
        "generated_here": False,
        "rendered_here": False,
        "verified_by": "contract only",
    }
    return {
        "ok": True,
        "verdict": "pass",
        "issues": [],
        "not_checked": ["whether the style renders as described is unverified by this contract"],
        "contract": contract,
    }


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = compile_codefilm_generation_record(params.get("record"))
    report_path = out_dir / "codefilm_generation_record_contract.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "verdict": report["verdict"],
            "executed_here": False,
        },
    )


def register_codefilm_generation_record_schema_capabilities_once() -> list[str]:
    """Register ``video.codefilm_generation_record_schema`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.codefilm_generation_record_schema",
            kind="video",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "record": {"type": "object"},
                },
                "required": ["record"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Code-film generation record schema (fake contract): a "
                "record naming style, category, materials and record "
                "operations; nothing is rendered or generated here."
            ),
        )
    )
    return ["video.codefilm_generation_record_schema"]


__all__ = [
    "compile_codefilm_generation_record",
    "register_codefilm_generation_record_schema_capabilities_once",
]
