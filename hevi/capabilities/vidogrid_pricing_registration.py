"""VidoGrid pricing registration (``model.vidogrid_pricing_registration``).

Clean-room registration of *published public-page facts only*, from
the VidoGrid homepage, pricing page, terms page and public API docs
as read on 2026-11-02 (read-only check: not signed in, no account
created, no generation run, no payment made). This module stores no
key, calls no API, and generates nothing. Every price it holds
carries a source and a date; any record without both is refused,
and any price the caller invents -- a tier, a number, a free model
that is not free -- is refused. Prices are marked ``unverified``
in the same sense as the Modal and Seedance registrations: the
public pages were read, not a live quote, and budgets must be
recomputed against the live pricing page at spend time.

Registered facts (2026-11-02 public pages):

- Free plan: $0, forever. Selected video and image models at no
  cost, one video at a time, no video extension. Fast-mode logo
  removal is included in the free plan.
- Free models: Veo 3.1 Fast/Lite in HD and Full HD (4 variants),
  Grok Imagine Video 1.5 Lite (10 variants), Vela AI (10 free
  generations per day, then pay-per-use), Nano Banana Pro / 2.1 /
  2 Lite, Grok Image.
- Not free (FREE column shown as "-"): Grok Imagine Video 1.5
  (all variants), Omni 1.1 Flash (all variants), GPT Image 2.5.
- Credits: $1 = 200 credits at the displayed bonus rate, minimum
  top-up $10, purchased credits never expire, failed renders are
  free, the cost is shown before generating.
- Listed pay-per-use figures (credits per generation): Veo 3.1
  Fast/Lite 4, Veo 2 20, Veo 3.1 HD/Full HD 100, Omni 1.1 Flash
  24, Grok Imagine Video 1.5 8-99 by resolution/duration, Grok
  Imagine Video 1.5 Lite from 2. The Veo Fast/Lite 4-credit
  figure is the listed pay-per-use figure; those models are free
  on the free plan.
- Monthly passes (Veo Max $20/month, Image Max $10/month) were
  displayed on the same pricing page together with "No special
  offers right now". They are recorded only as a note, never as
  current prices.
- Public API: REST v1, x-api-key header, webhook results,
  Premium availability; docs at https://docs.vidogrid.ai/.
- Account: Google sign-in, 18+, one account per person.
- Commercial use: Terms 8.1 -- the user owns their outputs and
  may use them for personal or commercial purposes, subject to
  the Terms, applicable law and the rights of others.

NOT verified (recorded as ``"unverified"``, never defaulted):
whether free outputs carry a logo, the free-plan queue rules,
free-tier API rate limits, and logged-in daily counters. None of
these may be stated as fact by a record that passes this check.

A registration goes stale 30 days after its ``price_as_of``
date: :func:`check_vidogrid_pricing_registration` then reports
``price_stale_recheck`` and the caller must re-verify before
budgeting. Nothing here authorises a spend.
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

_Registered = False

PRICE_SOURCE = (
    "VidoGrid public pages: homepage, pricing page, terms page, "
    "API docs (https://vidogrid.ai/, https://vidogrid.ai/pricing/, "
    "https://vidogrid.ai/terms/, https://docs.vidogrid.ai/) -- "
    "read-only check 2026-11-02, not signed in, no generation run"
)
PRICE_AS_OF = "2026-11-02"
STALE_AFTER_DAYS = 30

VIDOGRID_PRICING_URL = "https://vidogrid.ai/pricing/"
VIDOGRID_TERMS_URL = "https://vidogrid.ai/terms/"
VIDOGRID_API_DOCS_URL = "https://docs.vidogrid.ai/"
VIDOGRID_API_BASE_URL = "https://api.vidogrid.ai/uapi/v1"

# Free models exactly as listed FREE on the 2026-11-02 pricing page.
# No other model is free; adding one is a refusal, not an extension.
VIDOGRID_FREE_MODELS = (
    {"model": "Veo 3.1 Fast", "variant": "HD", "note": "one video at a time; cannot extend video"},
    {"model": "Veo 3.1 Fast", "variant": "Full HD", "note": "one video at a time; cannot extend video"},
    {"model": "Veo 3.1 Lite", "variant": "HD", "note": "one video at a time; cannot extend video"},
    {"model": "Veo 3.1 Lite", "variant": "Full HD", "note": "one video at a time; cannot extend video"},
    {"model": "Grok Imagine Video 1.5 Lite", "variant": "all 10 variants", "note": "all 10 listed variants FREE"},
    {"model": "Vela AI", "variant": "image", "note": "10 free generations per day, then pay-per-use"},
    {"model": "Nano Banana Pro", "variant": "image", "note": "FREE on the free plan"},
    {"model": "Nano Banana 2.1", "variant": "image", "note": "FREE on the free plan"},
    {"model": "Nano Banana 2 Lite", "variant": "image", "note": "FREE on the free plan"},
    {"model": "Grok Image", "variant": "image", "note": "FREE on the free plan"},
)

# Models whose FREE column is "-" on the same page: paid only.
VIDOGRID_PAID_ONLY_MODELS = (
    "Grok Imagine Video 1.5",
    "Omni 1.1 Flash",
    "GPT Image 2.5",
)

# Listed pay-per-use figures (credits per generation). The Veo
# Fast/Lite rows carry the listed pay-per-use figure; those models
# are free on the free plan (see VIDOGRID_FREE_MODELS).
VIDOGRID_PAY_PER_USE = (
    {"model": "Veo 3.1 Fast", "variant": "HD", "credits": 4},
    {"model": "Veo 3.1 Fast", "variant": "Full HD", "credits": 4},
    {"model": "Veo 3.1 Lite", "variant": "HD", "credits": 4},
    {"model": "Veo 3.1 Lite", "variant": "Full HD", "credits": 4},
    {"model": "Veo 2", "variant": "video", "credits": 20},
    {"model": "Veo 3.1", "variant": "HD", "credits": 100},
    {"model": "Veo 3.1", "variant": "Full HD", "credits": 100},
    {"model": "Omni 1.1 Flash", "variant": "all 5 variants", "credits": 24},
    {"model": "Grok Imagine Video 1.5", "variant": "all 9 variants", "credits_min": 8, "credits_max": 99},
    {"model": "Grok Imagine Video 1.5 Lite", "variant": "most variants", "credits_from": 2},
)

_UNVERIFIED_FIELDS = (
    "logo_on_free_outputs",
    "free_queue_rules",
    "free_tier_api_rate_limits",
    "logged_in_daily_counters",
)

_KNOWN_FREE_KEYS = {(e["model"], e["variant"]) for e in VIDOGRID_FREE_MODELS}
_KNOWN_PRICE_KEYS = {(e["model"], e["variant"]) for e in VIDOGRID_PAY_PER_USE}
_CANONICAL_PRICES = {(e["model"], e["variant"]): e for e in VIDOGRID_PAY_PER_USE}


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"model.vidogrid_pricing_registration: {detail}"}
    issue.update(extra)
    return issue


def vidogrid_pricing_record() -> dict[str, Any]:
    """The registered record: free tier, prices, API, account and terms facts."""
    return {
        "provider": "VidoGrid",
        "kind": "video_generation_studio",
        "route": "hosted",
        "pricing_source": {
            "url": VIDOGRID_PRICING_URL,
            "read_date": PRICE_AS_OF,
            "note": "Public pages read 2026-11-02; not re-fetched by this module and not a live price check",
        },
        "source": PRICE_SOURCE,
        "price_as_of": PRICE_AS_OF,
        "stale_after_days": STALE_AFTER_DAYS,
        "free_plan": {
            "price_usd": 0,
            "duration": "forever",
            "limits": ["one video at a time", "no video extension"],
            "fast_mode_logo_removal_included": True,
        },
        "free_models": [dict(entry) for entry in VIDOGRID_FREE_MODELS],
        "paid_only_models": list(VIDOGRID_PAID_ONLY_MODELS),
        "credit_rate": {
            "usd": 1,
            "credits": 200,
            "note": "displayed bonus rate (100 + 100%); struck-through base shown as $10 = 1,000 credits",
        },
        "minimum_top_up_usd": 10,
        "credits_never_expire": True,
        "failed_renders_free": True,
        "cost_shown_before_generation": True,
        "pay_per_use_credits": [dict(entry) for entry in VIDOGRID_PAY_PER_USE],
        "monthly_passes_note": (
            "The pricing page also displayed Veo Max ($20/month) and "
            "Image Max ($10/month) passes together with 'No special "
            "offers right now'. Passes are NOT registered as current "
            "prices; recheck the live page before any purchase."
        ),
        "api": {
            "version": "REST v1",
            "base_url": VIDOGRID_API_BASE_URL,
            "auth_header": "x-api-key",
            "webhook_results": True,
            "availability": "Premium",
            "docs_url": VIDOGRID_API_DOCS_URL,
        },
        "account": {
            "sign_in": "Google account",
            "minimum_age": 18,
            "one_account_per_person": True,
        },
        "commercial_use": (
            "Terms 8.1: the user owns their outputs and may use, "
            "publish, modify and sell them for personal or commercial "
            "purposes, subject to the Terms, applicable law and the "
            "rights of others."
        ),
        "unverified": {field: "unverified" for field in _UNVERIFIED_FIELDS},
        "account_registered": False,
        "api_key_stored": False,
        "api_connected": False,
        "generation_performed": False,
        "status": "unverified",
        "verified": False,
    }


def check_vidogrid_pricing_registration(record: Any, today: str | None = None) -> dict[str, Any]:
    """Judge a pricing record. Refuses unsourced or invented prices. Never raises."""
    issues: list[dict[str, Any]] = []
    if not isinstance(record, dict):
        return {
            "ok": False,
            "issues": [_issue("record_not_object", "pricing record must be an object")],
        }
    if not isinstance(record.get("source"), str) or not record["source"].strip():
        issues.append(_issue("price_source_missing", "every price needs a named source"))
    if not isinstance(record.get("price_as_of"), str) or not record["price_as_of"].strip():
        issues.append(_issue("price_date_missing", "every price needs a price_as_of date"))

    free_models = record.get("free_models")
    if not isinstance(free_models, list) or not free_models:
        issues.append(_issue("free_models_missing", "free_models must be a non-empty list"))
    else:
        seen_free: set[tuple[str, str]] = set()
        for entry in free_models:
            if not isinstance(entry, dict):
                issues.append(_issue("free_model_entry_invalid", "each free model must be an object"))
                continue
            key = (entry.get("model"), entry.get("variant"))
            seen_free.add(key)
            if entry.get("model") in VIDOGRID_PAID_ONLY_MODELS:
                issues.append(_issue(
                    "paid_only_model_listed_free",
                    f"model {entry.get('model')!r} is paid-only (FREE column '-'); it must not appear in free_models",
                    model=entry.get("model"),
                ))
            elif key not in _KNOWN_FREE_KEYS:
                issues.append(_issue(
                    "unknown_free_model",
                    f"free model {key!r} is not on the 2026-11-02 pricing page FREE list; invented free models are refused",
                    model=entry.get("model"),
                    variant=entry.get("variant"),
                ))
        for key in sorted(_KNOWN_FREE_KEYS):
            if key not in seen_free:
                issues.append(_issue(
                    "free_model_missing",
                    f"free model {key!r} from the pricing page FREE list is missing; the free table must be complete",
                    model=key[0],
                    variant=key[1],
                ))

    prices = record.get("pay_per_use_credits")
    if not isinstance(prices, list) or not prices:
        issues.append(_issue("pay_per_use_missing", "pay_per_use_credits must be a non-empty list"))
    else:
        seen_prices: set[tuple[str, str]] = set()
        for entry in prices:
            if not isinstance(entry, dict):
                issues.append(_issue("price_entry_invalid", "each pay-per-use price must be an object"))
                continue
            key = (entry.get("model"), entry.get("variant"))
            seen_prices.add(key)
            canonical = _CANONICAL_PRICES.get(key)
            if canonical is None:
                issues.append(_issue(
                    "unknown_price_tier",
                    f"price tier {key!r} is not in the registered price table; invented tiers are refused",
                    model=entry.get("model"),
                    variant=entry.get("variant"),
                ))
                continue
            for field, value in canonical.items():
                if field in ("model", "variant"):
                    continue
                if entry.get(field) != value:
                    issues.append(_issue(
                        "price_value_changed",
                        f"listed figure {field} for {key!r} must be {value!r} as published, got {entry.get(field)!r}",
                        model=key[0],
                        variant=key[1],
                    ))
        for key in sorted(_KNOWN_PRICE_KEYS):
            if key not in seen_prices:
                issues.append(_issue(
                    "price_entry_missing",
                    f"pay-per-use entry {key!r} is missing; the price table must be complete",
                    model=key[0],
                    variant=key[1],
                ))

    rate = record.get("credit_rate")
    if isinstance(rate, dict):
        if rate.get("usd") != 1 or rate.get("credits") != 200:
            issues.append(_issue(
                "credit_rate_changed",
                f"credit rate must be $1 = 200 credits as displayed, got {rate!r}",
            ))

    if isinstance(record.get("monthly_passes"), (list, dict)):
        issues.append(_issue(
            "monthly_passes_must_not_be_registered",
            "monthly passes are recorded only as a note; a passes price table must not be registered as current prices",
        ))

    unverified = record.get("unverified")
    if not isinstance(unverified, dict):
        issues.append(_issue("unverified_block_missing", "unverified block must be an object"))
    else:
        for field in _UNVERIFIED_FIELDS:
            if unverified.get(field) != "unverified":
                issues.append(_issue(
                    "unverified_field_overstated",
                    f"{field} was not verified on the public pages and must stay 'unverified', got {unverified.get(field)!r}",
                    field=field,
                ))

    if record.get("api_key") or record.get("key") or record.get("credential"):
        issues.append(_issue(
            "credential_must_not_be_stored",
            "this registration stores no key or credential",
        ))
    for flag in ("account_registered", "api_key_stored", "api_connected", "generation_performed"):
        if record.get(flag) is not False:
            issues.append(_issue(
                f"{flag}_must_be_false",
                f"{flag} must be false (registration only: no account, no key, no API connection, no generation)",
            ))
    if record.get("verified") is not False or record.get("status") != "unverified":
        issues.append(_issue(
            "record_must_stay_unverified",
            "the record must stay unverified (public pages read, no live quote, no generation run)",
        ))

    if isinstance(record.get("price_as_of"), str) and record["price_as_of"].strip():
        try:
            as_of = date.fromisoformat(record["price_as_of"].strip())
            check_day = date.fromisoformat(today) if today else date.today()
            if (check_day - as_of).days > STALE_AFTER_DAYS:
                issues.append(_issue(
                    "price_stale_recheck",
                    f"pricing is {(check_day - as_of).days} days old; re-verify against the live pricing page before budgeting",
                ))
        except ValueError:
            issues.append(_issue("price_date_invalid", "price_as_of must be an ISO date (YYYY-MM-DD)"))
    return {"ok": not issues, "record": record, "issues": issues}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            **_kwargs: Any) -> CapabilityResult:
    record = params.get("record") or vidogrid_pricing_record()
    report = check_vidogrid_pricing_registration(record, today=params.get("today"))
    report_path = Path(out_dir) / "vidogrid_pricing_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path),
            "verdict": "pass" if report["ok"] else "fail"},
    )


def register_vidogrid_pricing_capabilities_once() -> list[str]:
    """Register ``model.vidogrid_pricing_registration`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="model.vidogrid_pricing_registration",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "record": {"type": "object"},
                    "today": {"type": "string"},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "VidoGrid pricing registration: free plan ($0, forever, "
                "one video at a time, no extension) and free/paid model "
                "tables with source and date from the public pages read "
                "2026-11-02, credit rate $1 = 200, stale after 30 days. "
                "Logo-on-free-outputs, queue rules, free-tier API "
                "limits and logged-in counters stay unverified. No "
                "account, no key stored, no API, no spend authorised."
            ),
            line="model",
        )
    )
    return ["model.vidogrid_pricing_registration"]


register_vidogrid_pricing_capabilities_once()
