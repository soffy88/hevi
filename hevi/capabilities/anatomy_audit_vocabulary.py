"""Anatomy audit vocabulary gate (``qa.anatomy_audit_vocabulary``).

Clean-room restatement of the method in ``hevi-vs-explainer-skills-9.md``
section 2 item 1 (Anatomy): an explained mechanism must be mapped onto
one working machine, and the drawing must pass a geometry audit. This
module judges plans only, in hevi's own words:

1. Object-as-explanation mapping: every explained concept names the
   machine part that embodies it, the geometry that draws that part,
   and the label that names it on the page. Part, geometry, and label
   must correspond one to one; a part named twice, or a label with no
   part, fails.
2. Geometry audit: the plan must declare three self-checks, each with
   its evidence note -- no interpenetration of moving parts, every
   moving end landing on a real support, and overlap ordered by
   depth. A missing check, or a check declared without evidence,
   fails.

This module reads no media bytes, calls no generator, and touches no
budget. It never draws anything; it only judges whether a drawing
plan carries the mapping and the audit it claims.
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

_AUDIT_CHECKS = ("no_penetration", "seated_ends", "depth_order")


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_anatomy_audit(plan: Any) -> dict[str, Any]:
    """Judge one structure-explanation plan. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only.
    """
    issues: list[dict[str, Any]] = []
    mapping_out: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("plan_not_object", "anatomy plan must be a JSON object")],
            "mapping": [],
            "audit": {},
        }
    mapping = plan.get("mapping")
    if not isinstance(mapping, list) or not mapping:
        issues.append(
            _issue("mapping_missing", "plan must declare a non-empty mapping list")
        )
        mapping = mapping if isinstance(mapping, list) else []
    seen_parts: set[str] = set()
    seen_labels: set[str] = set()
    for index, entry in enumerate(mapping):
        if not isinstance(entry, dict):
            issues.append(
                _issue("mapping_entry_not_object", f"mapping[{index}] must be an object")
            )
            continue
        part = entry.get("part")
        geometry = entry.get("geometry")
        label = entry.get("label")
        if not _is_nonempty_str(part):
            issues.append(
                _issue("mapping_part_missing", f"mapping[{index}] must name a part")
            )
        if not _is_nonempty_str(geometry):
            issues.append(
                _issue(
                    "mapping_geometry_missing",
                    f"mapping[{index}] must name the geometry that draws the part",
                )
            )
        if not _is_nonempty_str(label):
            issues.append(
                _issue("mapping_label_missing", f"mapping[{index}] must name a label")
            )
        if _is_nonempty_str(part):
            if part in seen_parts:
                issues.append(
                    _issue("mapping_part_duplicate", f"part {part!r} is mapped twice")
                )
            seen_parts.add(part)
        if _is_nonempty_str(label):
            if label in seen_labels:
                issues.append(
                    _issue(
                        "mapping_label_duplicate",
                        f"label {label!r} is used for more than one part",
                    )
                )
            seen_labels.add(label)
        mapping_out.append(
            {"part": part, "geometry": geometry, "label": label}
        )
    audit = plan.get("audit")
    audit_out: dict[str, Any] = {}
    if not isinstance(audit, dict):
        issues.append(
            _issue("audit_missing", "plan must declare a geometry audit object")
        )
    else:
        for check in _AUDIT_CHECKS:
            entry = audit.get(check)
            if not isinstance(entry, dict):
                issues.append(
                    _issue(
                        "audit_check_missing",
                        f"audit must declare the {check} check",
                    )
                )
                continue
            evidence = entry.get("evidence")
            if not _is_nonempty_str(evidence):
                issues.append(
                    _issue(
                        "audit_evidence_missing",
                        f"audit check {check} must carry an evidence note",
                    )
                )
            audit_out[check] = {
                "declared": True,
                "evidence": evidence if _is_nonempty_str(evidence) else None,
            }
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "ok": verdict == "pass",
        "issues": issues,
        "mapping": mapping_out,
        "audit": audit_out,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_anatomy_audit(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "anatomy_audit_vocabulary_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "ok": report["ok"],
        },
    )


def register_anatomy_audit_vocabulary_capabilities_once() -> list[str]:
    """Register ``qa.anatomy_audit_vocabulary`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.anatomy_audit_vocabulary",
            kind="line",
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
            description=(
                "Anatomy audit vocabulary gate: a structure-explanation plan "
                "must map every concept onto one machine part with matching "
                "geometry and label, and must declare the three geometry "
                "audit checks (no penetration, seated ends, depth order) "
                "each with evidence. Plans are judged, never redrawn."
            ),
            line="qa",
        )
    )
    return ["qa.anatomy_audit_vocabulary"]


register_anatomy_audit_vocabulary_capabilities_once()
