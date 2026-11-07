"""Per-segment cost ledger (``video.segment_cost_ledger``).

Clean-room rewrite of the discipline in ``hevi-vs-digital-human-koubo-recheck.md``
item B1: the cost of a multi-segment piece is booked segment by
segment -- segment id, duration, resolution tier, credits or
cost, and the price source -- before the batch is judged against
its budget. A price without a source and a date is refused: the
ledger never invents a price, and no caller-supplied figure is
accepted without its provenance attached.

Registered schedule (recorded values only, NOT measured): the
per-second credit figures recorded in the recheck report --
720p 17 credits/second, 480p 10 credits/second -- are stored
with their source and date and flagged ``unverified``. They are
the figures as recorded from the vendor's published estimate,
never a measured spend, and budgets must be recomputed against
the live price at spend time. A caller rate that differs from
the registered schedule is accepted only with its own source
and date; an unsourced differing rate is refused.

This module is a *fake* backend: it records entries in a local
JSON ledger, totals them, and blocks an entry that would push
the ledger over a caller-supplied budget. It performs no network
call, stores no key, generates nothing, and connects to no
vendor. A real vendor route is a separate decision (registration,
login, and balance check by the account owner); this ledger is
the bookkeeping that must exist before any such call.
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

LEDGER_FILENAME = "segment_cost_ledger.json"

PRICE_SOURCE = (
    "hevi-vs-digital-human-koubo-recheck.md (2026-11-02): vendor "
    "published per-second credit estimate as recorded"
)
PRICE_AS_OF = "2026-11-02"

# Recorded per-second credit figures. Flagged unverified: recorded
# from the vendor's published estimate, never measured in hevi.
REGISTERED_RATES = (
    {"resolution": "480p", "credits_per_second": 10},
    {"resolution": "720p", "credits_per_second": 17},
)

_KNOWN_TIERS = {entry["resolution"]: entry["credits_per_second"]
                for entry in REGISTERED_RATES}


def _fail(message: str) -> None:
    raise CapabilityError(f"video.segment_cost_ledger: {message}")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def registered_renoise_rates() -> dict[str, Any]:
    """The registered schedule: rates, source, date, unverified flag."""
    return {
        "rates": [dict(entry) for entry in REGISTERED_RATES],
        "source": PRICE_SOURCE,
        "price_as_of": PRICE_AS_OF,
        "verified": False,
        "note": (
            "recorded figures from the vendor's published estimate; "
            "not measured in hevi; re-verify against the live price "
            "before budgeting a real spend"
        ),
    }


def _load_ledger(path: Path) -> dict[str, Any]:
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            _fail(f"ledger is not valid JSON: {path} ({exc})")
        if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
            _fail(f"ledger has no entries list: {path}")
        return data
    return {"capability": "video.segment_cost_ledger", "entries": []}


def _save_ledger(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _validate_entry(entry: Any) -> dict[str, Any]:
    """Validate one cost entry. Returns a normalised copy; raises on refusal."""
    if not isinstance(entry, dict):
        _fail("cost entry must be an object")
    segment_id = entry.get("segment_id")
    if not isinstance(segment_id, str) or not segment_id.strip():
        _fail("cost entry needs a non-empty segment_id")
    duration = entry.get("duration_s")
    if not _is_number(duration) or float(duration) <= 0:
        _fail("cost entry duration_s must be a positive number")
    tier = entry.get("resolution")
    if tier not in _KNOWN_TIERS:
        _fail(
            f"resolution {tier!r} is not a registered tier "
            f"({sorted(_KNOWN_TIERS)}); invented tiers are refused"
        )
    credits = entry.get("credits")
    if not _is_number(credits) or float(credits) < 0:
        _fail("cost entry credits must be a non-negative number")
    if not isinstance(entry.get("price_source"), str) \
            or not entry["price_source"].strip():
        _fail("cost entry without a price_source is refused: unsourced prices are not booked")
    if not isinstance(entry.get("price_as_of"), str) \
            or not entry["price_as_of"].strip():
        _fail("cost entry without a price_as_of date is refused")
    try:
        date.fromisoformat(entry["price_as_of"].strip())
    except ValueError:
        _fail("cost entry price_as_of must be an ISO date (YYYY-MM-DD)")
    rate = entry.get("rate_credits_per_second")
    if rate is not None:
        if not _is_number(rate) or float(rate) <= 0:
            _fail("rate_credits_per_second must be a positive number when present")
        if float(rate) != float(_KNOWN_TIERS[tier]):
            if not isinstance(entry.get("rate_source"), str) \
                    or not entry["rate_source"].strip() \
                    or not isinstance(entry.get("rate_as_of"), str) \
                    or not entry["rate_as_of"].strip():
                _fail(
                    "a rate differing from the registered schedule needs "
                    "its own rate_source and rate_as_of; unsourced "
                    "differing rates are refused"
                )
    if entry.get("api_key") or entry.get("key") or entry.get("credential"):
        _fail("this ledger stores no key or credential")
    return {
        "segment_id": segment_id,
        "duration_s": float(duration),
        "resolution": tier,
        "credits": float(credits),
        "rate_credits_per_second": (
            float(rate) if rate is not None else float(_KNOWN_TIERS[tier])
        ),
        "price_source": entry["price_source"],
        "price_as_of": entry["price_as_of"],
        "rate_source": entry.get("rate_source"),
        "rate_as_of": entry.get("rate_as_of"),
        "price_verified": False,
    }


def ledger_totals(data: dict[str, Any]) -> dict[str, Any]:
    """Totals over a loaded ledger: credits, duration, segment count."""
    entries = data.get("entries", [])
    return {
        "segments": len(entries),
        "total_credits": round(sum(float(e["credits"]) for e in entries), 6),
        "total_duration_s": round(sum(float(e["duration_s"]) for e in entries), 6),
    }


def record_segment_cost(ledger_path: Path, *, entry: dict[str, Any],
                        budget_credits: float | None = None) -> dict[str, Any]:
    """Book one segment cost. Raises on a refused entry or an over-budget ledger."""
    normalised = _validate_entry(entry)
    path = Path(ledger_path)
    data = _load_ledger(path)
    if any(e.get("segment_id") == normalised["segment_id"] for e in data["entries"]):
        _fail(f"duplicate segment_id in ledger: {normalised['segment_id']!r}")
    projected = ledger_totals(data)["total_credits"] + normalised["credits"]
    if budget_credits is not None:
        if not _is_number(budget_credits) or float(budget_credits) < 0:
            _fail("budget_credits must be a non-negative number when given")
        if projected > float(budget_credits):
            _fail(
                f"segment {normalised['segment_id']!r} would push the ledger "
                f"to {projected} credits, over the {float(budget_credits)} "
                "credit budget; the entry is blocked, not booked"
            )
    data["entries"].append(normalised)
    _save_ledger(path, data)
    totals = ledger_totals(data)
    return {"entry": normalised, "totals": totals, "ledger_path": str(path)}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            **_kwargs: Any) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = out_dir / LEDGER_FILENAME
    entry = params.get("entry")
    if entry is None:
        raise CapabilityError(
            "video.segment_cost_ledger: render needs an entry to book"
        )
    result = record_segment_cost(
        ledger_path, entry=entry,
        budget_credits=params.get("budget_credits"),
    )
    report = {
        "recorded": result["entry"],
        "totals": result["totals"],
        "registered_rates": registered_renoise_rates(),
    }
    report_path = out_dir / "segment_cost_ledger_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": "pass",
            "totals": result["totals"]},
    )


def register_segment_cost_ledger_capabilities_once() -> list[str]:
    """Register ``video.segment_cost_ledger`` (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.segment_cost_ledger",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "entry": {"type": "object"},
                    "budget_credits": {"type": "number"},
                },
                "required": ["entry"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Per-segment cost ledger (fake backend): segment id, "
                "duration, resolution tier, credits, and sourced price; "
                "unsourced prices refused, over-budget entries blocked. "
                "Registered rates are recorded, unverified figures. No "
                "vendor connection, no key, no spend."
            ),
            line="video",
        )
    )
    return ["video.segment_cost_ledger"]


register_segment_cost_ledger_capabilities_once()
