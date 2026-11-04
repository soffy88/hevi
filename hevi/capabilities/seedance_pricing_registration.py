"""Seedance pricing registration (``model.seedance_pricing_registration``).

Clean-room registration of *published list prices only*, from the
Volcano Ark Seedance 2.5 documentation and price conversions
recorded in ``hevi-vs-rain-before-stops.md`` (F3/F4, checked
2026-11-02). This module stores no key, calls no API, and
generates nothing. Every price it holds carries a source and a
date; any record without both is refused, and any price the
caller invents -- a tier, a number, a discount presented as the
list price -- is refused. Prices are marked ``unverified`` in the
same sense as the Modal registration: the fetched page text did
not itself carry a live quote, and budgets must be recomputed
against the Ark live price at spend time.

Registered list prices (per million tokens, token billing, billed
duration includes reference-video seconds):

- 480p / 720p: 70 yuan without video input, 42 yuan with video
  input (per the Ark token price table).
- 1080p: 77 yuan without video input, 46 yuan with video input.

Derived per-second figures (16:9, 24fps, no video input, from a
third-party conversion dated 2026-10-22: 480p ~0.67, 720p ~1.51,
1080p ~3.74 yuan/s) are stored separately, flagged ``derived``
and ``unverified``, and must never be used as the list price.
The 72%-discount figure (~2.7 yuan/s at 1080p) is a time-limited
promotion, recorded only as a note, never as a price.

A registration goes stale 30 days after its ``price_as_of``
date: ``check_seedance_pricing_registration`` then reports
``price_stale_recheck`` and the caller must re-verify before
budgeting. Nothing here authorises a spend.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.model_directory import record_in_directory
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

PRICE_SOURCE = "Volcano Ark Doubao-Seedance-2.5 model page + token price table"
PRICE_AS_OF = "2026-11-02"
DERIVED_SOURCE = "third-party conversion, 2026-10-22 (16:9, 24fps, no video input)"
STALE_AFTER_DAYS = 30

# List prices only. No other tier exists in the Ark table; adding
# one is a refusal, not an extension.
SEEDANCE_LIST_PRICES = (
    {
        "resolution": "480p",
        "token_price_per_million_cny": 70,
        "token_price_with_video_input_per_million_cny": 42,
    },
    {
        "resolution": "720p",
        "token_price_per_million_cny": 70,
        "token_price_with_video_input_per_million_cny": 42,
    },
    {
        "resolution": "1080p",
        "token_price_per_million_cny": 77,
        "token_price_with_video_input_per_million_cny": 46,
    },
)

# Derived per-second conversions. Kept apart from list prices and
# always flagged derived + unverified.
SEEDANCE_DERIVED_PER_SECOND = (
    {"resolution": "480p", "derived_cny_per_second": 0.67},
    {"resolution": "720p", "derived_cny_per_second": 1.51},
    {"resolution": "1080p", "derived_cny_per_second": 3.74},
)

_KNOWN_RESOLUTIONS = {entry["resolution"] for entry in SEEDANCE_LIST_PRICES}


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"model.seedance_pricing_registration: {detail}"}
    issue.update(extra)
    return issue


SEEDANCE_MODEL_ID = 'doubao-seedance-2.5-260628'

def seedance_pricing_record() -> dict[str, Any]:
    """The registered record: list prices + derived figures, sources and dates attached."""
    return {
        "model": "doubao-seedance-2.5-260628",
        "billing": "token billing; billed duration includes reference-video seconds",
        "list_prices": [dict(entry) for entry in SEEDANCE_LIST_PRICES],
        "derived_per_second_cny": [
            dict(entry) for entry in SEEDANCE_DERIVED_PER_SECOND
        ],
        "derived_figures_unverified": True,
        "source": PRICE_SOURCE,
        "derived_source": DERIVED_SOURCE,
        "price_as_of": PRICE_AS_OF,
        "discount_note": (
            "a time-limited 72% promotion (~2.7 yuan/s at 1080p) was "
            "reported 2026-09-06; it is not the list price and must "
            "not be budgeted as one"
        ),
        "recheck_note": "budgets must be recomputed against the Ark live price at spend time",
        "stale_after_days": STALE_AFTER_DAYS,
    }


def check_seedance_pricing_registration(record: Any,
                                        today: str | None = None) -> dict[str, Any]:
    """Judge a pricing record. Refuses unsourced or invented prices. Never raises."""
    issues: list[dict[str, Any]] = []
    if not isinstance(record, dict):
        return {
            "ok": False,
            "issues": [_issue("record_not_object", "pricing record must be an object")],
        }
    if not isinstance(record.get("source"), str) or not record["source"].strip():
        issues.append(_issue(
            "price_source_missing", "every price needs a named source",
        ))
    if not isinstance(record.get("price_as_of"), str) or not record["price_as_of"].strip():
        issues.append(_issue(
            "price_date_missing", "every price needs a price_as_of date",
        ))
    prices = record.get("list_prices")
    if not isinstance(prices, list) or not prices:
        issues.append(_issue(
            "list_prices_missing", "list_prices must be a non-empty list",
        ))
        return {"ok": False, "issues": issues}
    for entry in prices:
        if not isinstance(entry, dict):
            issues.append(_issue("price_entry_invalid", "each list price must be an object"))
            continue
        resolution = entry.get("resolution")
        if resolution not in _KNOWN_RESOLUTIONS:
            issues.append(_issue(
                "unknown_resolution_tier",
                f"resolution {resolution!r} is not in the Ark list-price table; "
                "invented tiers are refused",
                resolution=resolution,
            ))
        for key in (
            "token_price_per_million_cny",
            "token_price_with_video_input_per_million_cny",
        ):
            value = entry.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or float(value) <= 0:
                issues.append(_issue(
                    "price_value_invalid",
                    f"list price {key} for {resolution!r} must be a positive number",
                    resolution=resolution,
                ))
    derived = record.get("derived_per_second_cny")
    if derived is not None:
        if not isinstance(derived, list):
            issues.append(_issue(
                "derived_figures_invalid", "derived_per_second_cny must be a list when present",
            ))
        elif record.get("derived_figures_unverified") is not True:
            issues.append(_issue(
                "derived_figures_must_be_flagged_unverified",
                "derived per-second figures must be flagged derived_figures_unverified=true",
            ))
    if record.get("api_key") or record.get("key") or record.get("credential"):
        issues.append(_issue(
            "credential_must_not_be_stored",
            "this registration stores no key or credential",
        ))
    if isinstance(record.get("price_as_of"), str) and record["price_as_of"].strip():
        try:
            as_of = date.fromisoformat(record["price_as_of"].strip())
            check_day = date.fromisoformat(today) if today else date.today()
            if (check_day - as_of).days > STALE_AFTER_DAYS:
                issues.append(_issue(
                    "price_stale_recheck",
                    f"pricing is {(check_day - as_of).days} days old; "
                    "re-verify against the Ark live price before budgeting",
                ))
        except ValueError:
            issues.append(_issue(
                "price_date_invalid", "price_as_of must be an ISO date (YYYY-MM-DD)",
            ))
    return {"ok": not issues, "record": record, "issues": issues}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            **_kwargs: Any) -> CapabilityResult:
    record = params.get("record") or seedance_pricing_record()
    report = check_seedance_pricing_registration(record, today=params.get("today"))
    report_path = Path(out_dir) / "seedance_pricing_report.json"
    action = str(params.get("action") or "describe")
    if action not in ("describe", "record"):
        raise CapabilityError(
            "hevi/capabilities/seedance_pricing_registration.py: unknown action " + repr(action)
            + " (expected 'describe' or 'record')"
        )
    if action == "record" and not report["ok"]:
        raise CapabilityError(
            "hevi/capabilities/seedance_pricing_registration.py: refusing to record a failing pricing record"
        )
    directory_path = params.get("directory_path")
    if action == "record" and not directory_path:
        raise CapabilityError(
            "hevi/capabilities/seedance_pricing_registration.py: action='record' needs directory_path"
        )
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result = CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path),
            "verdict": "pass" if report["ok"] else "fail"},
    )
    if action == "record":
        recorded = record_in_directory(
            Path(str(directory_path)),
            {SEEDANCE_MODEL_ID: record},
        )
        result.qa["directory"] = str(directory_path)
        result.qa["recorded"] = sorted(recorded)
    return result


def register_seedance_pricing_capabilities_once() -> list[str]:
    """Register ``model.seedance_pricing_registration`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="model.seedance_pricing_registration",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "record": {"type": "object"},
                    "today": {"type": "string"},
                    "action": {"type": "string",
                               "enum": ["describe", "record"]},
                    "directory_path": {"type": "string"},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Seedance list-price registration: Ark published "
                "token prices with source and date, derived "
                "per-second figures flagged unverified, stale after "
                "30 days. No API, no key stored, no spend authorised."
            ),
            line="model",
        )
    )
    return ["model.seedance_pricing_registration"]


register_seedance_pricing_capabilities_once()
