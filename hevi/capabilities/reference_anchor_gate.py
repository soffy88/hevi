"""Reference-picture anchor gate (``qa.reference_anchor_gate``).

Clean-room restatement of the tutorial method in
``hevi-vs-3d-cartoon-tutorial-6steps.md`` section 2 item 2: a style
is fixed by showing 3-5 reference pictures before any test render,
and the style is not lengthened until the test matches. In hevi's
caliber the anchor is a judged plan:

1. Between 3 and 5 reference pictures must be declared, each with a
   sha256, a source, and at least one anchor dimension drawn from
   the closed vocabulary: proportion, stroke, palette, lighting,
   material.
2. Every reference must declare its rights from the closed
   vocabulary: self_owned, licensed, public_domain, authorized.
   An undeclared or out-of-vocabulary rights value fails.
3. Duplicate sha256 values fail: the same picture cannot anchor
   twice.

This module judges plans only. It downloads no pictures and
verifies no rights claim; the declaration is the auditable record.
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

_DIMENSIONS = ("proportion", "stroke", "palette", "lighting", "material")
_RIGHTS = ("self_owned", "licensed", "public_domain", "authorized")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_reference_anchors(plan: Any) -> dict[str, Any]:
    """Judge one reference-anchor plan. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only.
    """
    issues: list[dict[str, Any]] = []
    refs_out: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("plan_not_object", "plan must be an object")],
            "references": [],
        }
    references = plan.get("references")
    if not isinstance(references, list):
        issues.append(
            _issue("references_missing", "plan must declare a 'references' list")
        )
        references = []
    if isinstance(plan.get("references"), list) and not 3 <= len(references) <= 5:
        issues.append(
            _issue(
                "reference_count_out_of_range",
                f"expected 3-5 references, got {len(references)}",
            )
        )
    seen: set[str] = set()
    for index, ref in enumerate(references):
        if not isinstance(ref, dict):
            issues.append(_issue("reference_not_object", f"references[{index}] must be an object"))
            continue
        sha = ref.get("sha256")
        if not isinstance(sha, str) or not _SHA_RE.match(sha):
            issues.append(
                _issue("reference_sha_invalid", f"references[{index}] sha256 must be 64 hex chars")
            )
        elif sha in seen:
            issues.append(
                _issue("reference_sha_duplicate", f"references[{index}] sha256 repeats an earlier reference")
            )
        else:
            seen.add(sha)
        if not _is_nonempty_str(ref.get("source")):
            issues.append(
                _issue("reference_source_missing", f"references[{index}] must declare a source")
            )
        dims = ref.get("anchor_dimensions")
        if not isinstance(dims, list) or not dims:
            issues.append(
                _issue(
                    "anchor_dimensions_missing",
                    f"references[{index}] must declare at least one anchor dimension",
                )
            )
        elif any(dim not in _DIMENSIONS for dim in dims):
            issues.append(
                _issue(
                    "anchor_dimension_unknown",
                    f"references[{index}] anchor dimensions must be drawn from {_DIMENSIONS}",
                )
            )
        if ref.get("rights") not in _RIGHTS:
            issues.append(
                _issue(
                    "reference_rights_undeclared",
                    f"references[{index}] rights must be one of {_RIGHTS}",
                )
            )
        refs_out.append({"sha256": sha if isinstance(sha, str) else None})
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "ok": verdict == "pass",
        "issues": issues,
        "references": refs_out,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_reference_anchors(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "reference_anchor_gate_report.json"
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


def register_reference_anchor_gate_capabilities_once() -> list[str]:
    """Register ``qa.reference_anchor_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.reference_anchor_gate",
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
                "Reference-picture anchor gate: 3-5 references, each with "
                "a sha256, a source, anchor dimensions from a closed "
                "vocabulary, and declared rights. Plans are judged, "
                "never fetched."
            ),
            line="qa",
        )
    )
    return ["qa.reference_anchor_gate"]


register_reference_anchor_gate_capabilities_once()
