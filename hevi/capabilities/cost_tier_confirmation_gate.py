"""Cost-tier confirmation gate (``qa.cost_tier_confirmation_gate``).

Clean-room rewrite of the *method* in the rea-video field report
(``hevi-vs-rea-video.md`` section 2.2, cost and confirmation):
expensive generation is never the first step. A remake plan
walks four confirmation tiers in order -- G1 budget, G2
storyboard plus keyframes, G3 low-resolution draft, G4
upscaled finish -- and cheap keyframes are confirmed before
the expensive video is generated. Already-produced units are
cached under the key (input hash, model, parameters), so a
repeat never pays twice. Skipping a tier without a recorded
confirmation fails.

H3 entries must be tier-partitioned: the 15-second API tier
and the 30-second pixstag tier are different routes and must
never be merged into one tier entry. Prices recorded anywhere
near this gate are third-party figures and must never be used
as thresholds; this gate judges confirmations, not prices.

Shape: ``{"tiers": [{"tier": "G1", "confirmed": bool,
"confirmation_ref"}], "units": [{"id", "cache_key": {"input_hash",
"model", "params"}}], "h3_entries": [{"id", "tier",
"tier_max_s"}]}``. Tiers must appear in G1..G4 order and every
tier before the first unconfirmed tier must itself be
confirmed; a G4 step with any earlier tier unconfirmed fails.
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

TIERS = ("G1", "G2", "G3", "G4")
H3_TIERS = {
    "h3_api_15s": 15,
    "pixstag_30s": 30,
}


def check_cost_tier_confirmation(plan: dict[str, Any] | None) -> dict[str, Any]:
    """Judge whether a remake plan walks the confirmation tiers."""
    issues: list[str] = []
    if not isinstance(plan, dict):
        raise CapabilityError("cost-tier plan must be an object")
    tiers = plan.get("tiers")
    if not isinstance(tiers, list) or not tiers:
        issues.append("missing_tiers: plan declares no confirmation tiers")
        return {"verdict": "fail", "ok": False, "issues": issues}
    seen: list[str] = []
    for entry in tiers:
        if not isinstance(entry, dict):
            issues.append("tier_not_object")
            continue
        tier = entry.get("tier")
        if tier not in TIERS:
            issues.append(f"unknown_tier: {tier!r}")
            continue
        if tier in seen:
            issues.append(f"duplicate_tier: {tier}")
        seen.append(tier)
        if tier != TIERS[len(seen) - 1]:
            issues.append(f"tier_out_of_order: {tier} out of G1..G4 order")
        if not entry.get("confirmed") and not entry.get("confirmation_ref"):
            issues.append(f"tier_unconfirmed: {tier} without confirmation")
    confirmed = {
        e.get("tier")
        for e in tiers
        if isinstance(e, dict) and e.get("confirmed")
    }
    if "G4" in seen and not {"G1", "G2", "G3"} <= confirmed:
        issues.append(
            "tier_skipped: G4 reached while an earlier tier is unconfirmed; "
            "cheap keyframes must be confirmed before expensive generation"
        )
    units = plan.get("units", [])
    if not isinstance(units, list):
        issues.append("units_not_list")
        units = []
    for unit in units:
        if not isinstance(unit, dict):
            issues.append("unit_not_object")
            continue
        key = unit.get("cache_key")
        if not isinstance(key, dict) or not (
            key.get("input_hash") and key.get("model") and "params" in key
        ):
            issues.append(
                f"bad_cache_key: unit {unit.get('id')!r} cache key must be "
                "(input_hash, model, params)"
            )
    for entry in plan.get("h3_entries", []):
        if not isinstance(entry, dict):
            issues.append("h3_entry_not_object")
            continue
        tier = entry.get("tier")
        if tier not in H3_TIERS:
            issues.append(
                f"h3_tier_unpartitioned: entry {entry.get('id')!r} tier "
                f"{tier!r}; H3 entries must be h3_api_15s or pixstag_30s"
            )
        elif entry.get("tier_max_s") != H3_TIERS[tier]:
            issues.append(
                f"h3_tier_mismatch: entry {entry.get('id')!r} tier {tier} "
                f"must carry tier_max_s {H3_TIERS[tier]}"
            )
    verdict = "fail" if issues else "pass"
    return {"verdict": verdict, "ok": not issues, "issues": issues}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_cost_tier_confirmation(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "cost_tier_confirmation.json"
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


def register_cost_tier_confirmation_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.cost_tier_confirmation_gate",
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
                "Cost-tier confirmation gate (rea-video A6, "
                "clean-room): G1..G4 in order, cheap keyframes "
                "confirmed before expensive generation, H3 entries "
                "tier-partitioned. See REA_VIDEO_ATTRIBUTION.md."
            ),
            line="qa",
        )
    )
    return ["qa.cost_tier_confirmation_gate"]


register_cost_tier_confirmation_gate_capabilities_once()
