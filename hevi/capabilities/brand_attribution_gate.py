"""Brand attribution honesty gate (``qa.brand_attribution_gate``).

Discipline gate only. Motion recipes are described as restated
from studying the motion language of other makers' product films,
with no original material, no brand assets, and no affiliation or
endorsement. A plan may therefore name only the brands on the
closed acknowledgements list, must declare that there is no
affiliation and no endorsement, and must never claim that a
single card can be traced to a single source film: no per-card
provenance is recorded anywhere. Any brand outside the closed
list fails, including names that appear in promotional copy but
not in the acknowledgements. This gate judges the plan only and
renders nothing. See VIDEO_SHOTCRAFT_ATTRIBUTION.md.
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

# Closed acknowledgements list, in the order the upstream
# acknowledgements name them. Nothing may be added to it here.
ACKNOWLEDGED_BRANDS: tuple[str, ...] = (
    "ClickUp",
    "Perplexity",
    "Slack",
    "Notion",
    "Figma",
    "Framer",
    "Bear",
    "Raycast",
    "Pitch",
    "Miro",
    "Superhuman",
    "Loom",
)


def acknowledged_brands() -> frozenset[str]:
    """Return the closed acknowledgements brand vocabulary."""
    return frozenset(ACKNOWLEDGED_BRANDS)


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_brand_attribution(plan: Any) -> dict[str, Any]:
    """Validate a brand-attribution plan. Never raises.

    Verdicts are ``pass`` / ``fail`` only. Every named brand must
    sit on the closed list, no affiliation and no endorsement
    must be declared, and no per-card provenance or original-asset
    claim is admitted.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("plan_not_object", "plan must be a JSON object")],
            "brands": [],
        }
    brands = plan.get("brands")
    if not isinstance(brands, list):
        issues.append(_issue("brands_missing", "plan must declare a brands list"))
        brands_out: list[str] = []
    else:
        brands_out = [b for b in brands if isinstance(b, str)]
        unknown = [b for b in brands_out if b not in ACKNOWLEDGED_BRANDS]
        if unknown:
            issues.append(
                _issue(
                    "brand_not_acknowledged",
                    f"brands outside the closed list: {unknown}",
                )
            )
    if plan.get("no_affiliation_declared") is not True:
        issues.append(
            _issue(
                "affiliation_undeclared",
                "plan must declare that there is no affiliation",
            )
        )
    if plan.get("no_endorsement_declared") is not True:
        issues.append(
            _issue(
                "endorsement_undeclared",
                "plan must declare that there is no endorsement",
            )
        )
    if plan.get("per_card_provenance_claimed") is True:
        issues.append(
            _issue(
                "per_card_provenance_claimed",
                "no per-card provenance to a single source film is recorded anywhere",
            )
        )
    if plan.get("original_assets_claimed") is True:
        issues.append(
            _issue(
                "original_assets_claimed",
                "no original brand material or brand asset is used",
            )
        )
    if plan.get("methods_rewritten_declared") is not True:
        issues.append(
            _issue(
                "methods_rewritten_undeclared",
                "plan must declare that the methods are restated in hevi's own terms",
            )
        )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "brands": brands_out,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_brand_attribution(params.get("plan"))
    report_path = out_dir / "brand_attribution.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_brand_attribution_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.brand_attribution_gate",
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
            layer="oskill",
            description=(
                "Brand attribution honesty gate: only the closed "
                "acknowledgements brands may be named, no "
                "affiliation and no endorsement must be declared, "
                "and no per-card provenance or original-asset "
                "claim is admitted."
            ),
        )
    )
    return ["qa.brand_attribution_gate"]


__all__ = [
    "ACKNOWLEDGED_BRANDS",
    "acknowledged_brands",
    "check_brand_attribution",
    "register_brand_attribution_gate_capabilities_once",
]
