"""Real-material isolation gate (``qa.real_material_isolation_gate``).

Clean-room rewrite of the *method* in the rea-video field report
(``hevi-vs-rea-video.md`` section 2.1 item 5): when a finished
film embeds real material -- a photograph, a clip, a screenshot
-- that material is evidence, not a prompt. It goes into an
isolation area (``user_assets``) and must be supplied by the
caller; a model must never be asked to regenerate it as a
substitute. Embedded pictures whose provenance is unconfirmed
default to "real or AI, unconfirmed" and stay in the isolation
area until confirmed. The gate judges the plan record: any step
that generates a declared real asset fails, and any embedded
picture recorded as confirmed-real without a confirmation record
fails.

Shape: ``{"user_assets": [{"id", "kind", "confirmed": bool,
"confirmation_ref"}], "embedded": [{"id", "status"}], "steps":
[{"id", "action", "target_asset_id"}]}``. ``action`` is
``"generate"`` or ``"use_asset"``. ``status`` is
``"real_or_ai_unconfirmed"``, ``"confirmed_real"`` or
``"confirmed_generated"``.
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

EMBEDDED_STATUSES = (
    "real_or_ai_unconfirmed",
    "confirmed_real",
    "confirmed_generated",
)


def check_real_material_isolation(plan: dict[str, Any] | None) -> dict[str, Any]:
    """Judge whether real material stays isolated from generation."""
    issues: list[str] = []
    if not isinstance(plan, dict):
        raise CapabilityError("real-material plan must be an object")
    assets = plan.get("user_assets")
    if not isinstance(assets, list):
        issues.append("user_assets_not_list")
        assets = []
    asset_ids = set()
    for asset in assets:
        if not isinstance(asset, dict) or not asset.get("id"):
            issues.append("asset_without_id")
            continue
        asset_ids.add(asset["id"])
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        if asset.get("confirmed") and not asset.get("confirmation_ref"):
            issues.append(
                f"unconfirmed_confirmation: asset {asset['id']!r} marked "
                "confirmed without a confirmation_ref"
            )
    embedded = plan.get("embedded", [])
    if not isinstance(embedded, list):
        issues.append("embedded_not_list")
        embedded = []
    for item in embedded:
        if not isinstance(item, dict):
            issues.append("embedded_not_object")
            continue
        if item.get("status") not in EMBEDDED_STATUSES:
            issues.append(
                f"bad_embedded_status: {item.get('id')!r} status "
                f"{item.get('status')!r}; unconfirmed material must stay "
                "'real_or_ai_unconfirmed'"
            )
        elif item.get("status") == "confirmed_real" and not item.get("confirmation_ref"):
            issues.append(
                f"unconfirmed_confirmation: embedded {item.get('id')!r} "
                "marked confirmed_real without a confirmation_ref"
            )
    steps = plan.get("steps", [])
    if not isinstance(steps, list):
        issues.append("steps_not_list")
        steps = []
    for step in steps:
        if not isinstance(step, dict):
            issues.append("step_not_object")
            continue
        if step.get("action") == "generate" and step.get("target_asset_id") in asset_ids:
            issues.append(
                f"model_substitute_for_real: step {step.get('id')!r} "
                f"generates declared real asset {step['target_asset_id']!r}; "
                "real material must be supplied, never regenerated"
            )
    verdict = "fail" if issues else "pass"
    return {"verdict": verdict, "ok": not issues, "issues": issues}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_real_material_isolation(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "real_material_isolation.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "verdict": report["verdict"],
            "ok": report["ok"],
        },
    )


_Registered = False


def register_real_material_isolation_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.real_material_isolation_gate",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {"plan": {"type": "object"}},
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Real-material isolation gate (rea-video A3, "
                "clean-room): real material lives in user_assets and "
                "must be supplied, never regenerated; unconfirmed "
                "embedded pictures stay 'real_or_ai_unconfirmed'. See "
                "REA_VIDEO_ATTRIBUTION.md."
            ),
            line="qa",
        )
    )
    return ["qa.real_material_isolation_gate"]


register_real_material_isolation_gate_capabilities_once()
