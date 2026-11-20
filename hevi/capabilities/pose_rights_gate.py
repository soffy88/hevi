"""Rights and attribution gate (``qa.pose_rights_gate``).

Rights discipline for every pose-gallery reference, across
all three source lines (giaaibusi, CharaDB, Shisei): the
upstream MIT grant covers source code only; images under
``img/`` and ``thumbs/`` and original data under ``data/``
belong to the original author. Use is non-commercial
reference only, redistribution is forbidden, attribution
is mandatory, and the gallery is removed on the author's
objection. Portrait entries carry the unresolved CC0
tension (README says CC0 1.0, LICENSE scope note says
non-commercial); CharaDB entries additionally forbid
real-person and minor use; Shisei entries must note their
LICENSE-images/NOTICE files, whose contents were never
read in full.
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

SOURCES: frozenset[str] = frozenset({"giaaibusi", "charadb", "shisei"})
KINDS: frozenset[str] = frozenset({"pose", "costume", "portrait"})


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_pose_rights(decl: Any) -> dict[str, Any]:
    """Validate one rights and attribution declaration.

    Verdicts are ``pass`` / ``fail`` only. A declaration fails
    when the source is unknown, commercial use or
    redistribution is claimed, attribution is missing, removal
    on objection is not promised, or a source-specific
    condition is unmet (CharaDB real-person/minor ban, Shisei
    license note, portrait CC0 tension acknowledgment).
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(decl, dict):
        return fail("rights_not_object", "rights declaration must be a JSON object")
    source = decl.get("source")
    if source not in SOURCES:
        return fail(
            "unknown_source",
            f"rights source must be one of {sorted(SOURCES)}, got {source!r}",
        )
    kind = decl.get("kind")
    if kind is not None and kind not in KINDS:
        return fail(
            "unknown_kind",
            f"kind must be one of {sorted(KINDS)}, got {kind!r}",
        )
    if decl.get("commercial_use") is not False:
        return fail(
            "commercial_use_refused",
            "pose-gallery material is non-commercial reference only; "
            "commercial_use must be explicitly false",
        )
    if decl.get("redistribute") is not False:
        return fail(
            "redistribution_refused",
            "pose-gallery images and data must not be repackaged or "
            "resold; redistribute must be explicitly false",
        )
    if decl.get("attribution") is not True:
        return fail(
            "attribution_missing",
            "the original author must be attributed; attribution must be explicitly true",
        )
    if decl.get("objection_removal") is not True:
        return fail(
            "objection_removal_missing",
            "the gallery must be removed on the author's objection; "
            "objection_removal must be explicitly true",
        )
    if source == "charadb" and decl.get("no_real_person_or_minor") is not True:
        return fail(
            "charadb_condition_unmet",
            "CharaDB images must never be used for real people or "
            "minors; no_real_person_or_minor must be explicitly true",
        )
    if source == "shisei" and decl.get("shisei_license_noted") is not True:
        return fail(
            "shisei_license_unnoted",
            "Shisei images carry LICENSE-images and NOTICE files "
            "whose contents were never read in full; the record "
            "must note them (shisei_license_noted true)",
        )
    if kind == "portrait" and decl.get("cc0_tension_acknowledged") is not True:
        return fail(
            "cc0_tension_unacknowledged",
            "portrait CC0 1.0 (README) versus non-commercial "
            "(LICENSE scope note) is unresolved; the record must "
            "acknowledge the tension",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "source": source,
        "kind": kind,
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_pose_rights(params.get("rights"))
    report_path = out_dir / "pose_rights_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_pose_rights_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.pose_rights_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "rights": {"type": "object"},
                },
                "required": ["rights"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Pose-gallery rights gate: MIT covers code only, "
                "images belong to the original author, non-commercial "
                "reference only, no redistribution, attribution "
                "mandatory, removal on objection, source-specific "
                "conditions enforced."
            ),
        )
    )
    return ["qa.pose_rights_gate"]


__all__ = [
    "KINDS",
    "SOURCES",
    "check_pose_rights",
    "register_pose_rights_gate_capabilities_once",
]
