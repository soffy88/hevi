"""Capability-map schema (``model.capability_map_schema``).

Clean-room rewrite of the *schema discipline* in the rea-video
field report (``hevi-vs-rea-video.md`` section 2.2): routing
decisions are made against capability primitives, not vendor
names. The map has three layers -- signals (observable shot
features), primitives (vendor-neutral capability atoms), and
model entries (concrete routes). Every model entry carries its
boundary, its price, its licence, its verification date, and a
confidence; entries older than 90 days at the caller's
``today`` are stale and must be re-verified before use.

Prices in this map are third-party figures recorded as
``unverified``. They are never thresholds: a price that lacks
a source or a verification date fails validation, and no entry
may claim a verified price. H3 entries must carry the tier
partition (``h3_api_15s`` or ``pixstag_30s``); an unpartitioned
H3 entry fails. This schema judges documents only; it calls no
model and holds no key.

Shape: ``{"signals": [...], "primitives": [{"id", "kind"}],
"models": [{"id", "primitive_ids": [...], "boundary", "price":
{"amount", "unit", "source", "verified": bool}, "license",
"verified_date", "confidence", "tier"}]}``.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

EXPIRY_DAYS = 90
H3_TIERS = ("h3_api_15s", "pixstag_30s")


def _parse_date(value: Any, where: str, issues: list[str]) -> date | None:
    if not isinstance(value, str):
        issues.append(f"bad_verified_date: {where} {value!r} is not a date string")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        issues.append(f"bad_verified_date: {where} {value!r} is not ISO format")
        return None


def validate_capability_map(
    document: dict[str, Any] | None, *, today: str
) -> dict[str, Any]:
    """Validate a signals/primitives/models capability map document."""
    issues: list[str] = []
    if not isinstance(document, dict):
        raise CapabilityError("capability map must be an object")
    today_date = _parse_date(today, "today", issues)
    if today_date is None:
        return {"verdict": "fail", "ok": False, "issues": issues}
    signals = document.get("signals")
    if not isinstance(signals, list) or not signals:
        issues.append("missing_signals: map declares no signals")
    primitives = document.get("primitives")
    primitive_ids: set[str] = set()
    if not isinstance(primitives, list) or not primitives:
        issues.append("missing_primitives: map declares no primitives")
        primitives = []
    for primitive in primitives:
        if not isinstance(primitive, dict) or not primitive.get("id"):
            issues.append("primitive_without_id")
            continue
        primitive_ids.add(primitive["id"])
    models = document.get("models")
    if not isinstance(models, list) or not models:
        issues.append("missing_models: map declares no model entries")
        models = []
    stale: list[str] = []
    for model in models:
        if not isinstance(model, dict) or not model.get("id"):
            issues.append("model_without_id")
            continue
        model_id = model["id"]
        for primitive_id in model.get("primitive_ids", []):
            if primitive_id not in primitive_ids:
                issues.append(
                    f"dangling_primitive: model {model_id!r} references "
                    f"undeclared primitive {primitive_id!r}"
                )
        if not model.get("boundary"):
            issues.append(f"model_without_boundary: {model_id!r}")
        price = model.get("price")
        if not isinstance(price, dict):
            issues.append(f"model_without_price: {model_id!r}")
        else:
            if price.get("verified") is True:
                issues.append(
                    f"price_claimed_verified: model {model_id!r} price is "
                    "third-party and must stay unverified"
                )
            if not price.get("source"):
                issues.append(f"price_without_source: model {model_id!r}")
            if price.get("amount") is None or not price.get("unit"):
                issues.append(f"price_incomplete: model {model_id!r}")
        if not model.get("license"):
            issues.append(f"model_without_license: {model_id!r}")
        verified = _parse_date(model.get("verified_date"), f"model {model_id!r}", issues)
        if verified is not None and (today_date - verified).days > EXPIRY_DAYS:
            stale.append(model_id)
            issues.append(
                f"stale_entry: model {model_id!r} verified "
                f"{model['verified_date']} is over {EXPIRY_DAYS} days old"
            )
        confidence = model.get("confidence")
        if confidence not in ("low", "medium", "high"):
            issues.append(f"bad_confidence: model {model_id!r} {confidence!r}")
        if "h3" in model_id.lower() or model.get("provider") == "minimax_h3":
            if model.get("tier") not in H3_TIERS:
                issues.append(
                    f"h3_tier_unpartitioned: model {model_id!r} must carry "
                    "tier h3_api_15s or pixstag_30s"
                )
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "ok": not issues,
        "issues": issues,
        "stale_entries": stale,
        "expiry_days": EXPIRY_DAYS,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = validate_capability_map(params.get("document"), today=params.get("today"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "capability_map_validation.json"
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


def register_capability_map_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="model.capability_map_schema",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "document": {"type": "object"},
                    "today": {"type": "string"},
                },
                "required": ["document", "today"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Capability-map schema (rea-video B2, clean-room): "
                "signals to primitives to model entries, 90-day "
                "expiry, prices always third-party/unverified, H3 "
                "entries tier-partitioned. See "
                "REA_VIDEO_ATTRIBUTION.md."
            ),
            line="model",
        )
    )
    return ["model.capability_map_schema"]


register_capability_map_schema_capabilities_once()
