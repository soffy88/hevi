"""Quote confirmation gate (``qa.quote_confirmation_gate``).

Clean-room rewrite of a *method* only: before any paid generation
runs, the caller shows a cost quote and the user confirms it in their
own words. A host popup, a prior blanket "just generate", or a
missing confirmation is not confirmation. No text, code, or asset
from any outside repository is copied here. See
VIBE_KNOWLEDGE_ATTRIBUTION.md.

The confirmation semantics reuse the ``spend_brake`` discipline:
``confirmed`` must be exactly ``True``, and a batch larger than one
needs a passing smoke run. When the quote carries a storyboard, the
check is delegated to ``spend_brake.gate_spend`` itself; otherwise
the same two rules are applied inline to the quote.
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
from hevi.capabilities.spend_brake import gate_spend

_Registered = False

CONFIRMATION_SOURCES = ("user_verbatim",)


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_quote_confirmation(quote: Any) -> dict[str, Any]:
    """Judge one cost quote plus confirmation. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(quote, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue("quote_not_object", "quote must be a JSON object")
            ],
            "allowed": False,
            "blockers": ["quote must be a JSON object"],
        }
    estimate = quote.get("estimate")
    if not isinstance(estimate, dict):
        issues.append(
            _issue(
                "estimate_missing",
                "quote must carry an estimate object with items and a total",
            )
        )
        estimate = {}
    items = estimate.get("items") if isinstance(estimate, dict) else None
    if not isinstance(items, list) or not items:
        issues.append(
            _issue(
                "estimate_items_missing",
                "estimate must list at least one priced item",
            )
        )
    total = estimate.get("total_credits") if isinstance(estimate, dict) else None
    if not _is_number(total) or total < 0:
        issues.append(
            _issue(
                "estimate_total_invalid",
                "estimate must declare a non-negative total_credits",
            )
        )
    confirmation = quote.get("confirmation")
    if not isinstance(confirmation, dict):
        issues.append(
            _issue(
                "confirmation_missing",
                "quote must carry a confirmation object",
            )
        )
        confirmation = {}
    confirmed = confirmation.get("confirmed")
    source = confirmation.get("source")
    verbatim = confirmation.get("verbatim")
    if confirmed is not True:
        issues.append(
            _issue(
                "confirmed_not_true",
                "confirmation.confirmed must be exactly true; a missing "
                "field, the string 'true', or 1 is not confirmation",
            )
        )
    if source not in CONFIRMATION_SOURCES:
        issues.append(
            _issue(
                "confirmation_source_invalid",
                "confirmation.source must be user_verbatim: a host popup, "
                "a prior blanket instruction, or any other source is not "
                "a confirmation of this quote",
            )
        )
    if source == "user_verbatim" and not _is_nonempty_str(verbatim):
        issues.append(
            _issue(
                "confirmation_verbatim_missing",
                "a user_verbatim confirmation must carry the user's own "
                "confirming words verbatim",
            )
        )
    batch_size = quote.get("batch_size", 1)
    smoke_passed = quote.get("smoke_passed")
    storyboard = quote.get("storyboard")
    if isinstance(storyboard, list):
        delegated = gate_spend(
            storyboard,
            confirmed=confirmed,
            smoke_passed=smoke_passed,
            batch_size=batch_size,
        )
        for blocker in delegated["blockers"]:
            issues.append(_issue("spend_brake_blocker", blocker))
    else:
        if not _is_number(batch_size) or int(batch_size) != batch_size or int(batch_size) < 1:
            issues.append(
                _issue(
                    "batch_size_invalid",
                    "batch_size must be a whole number of at least 1",
                )
            )
        elif int(batch_size) > 1 and smoke_passed is not True:
            issues.append(
                _issue(
                    "smoke_missing",
                    "a batch larger than one needs a passing smoke run on "
                    "record before spending",
                )
            )
    blockers = [issue["detail"] for issue in issues]
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "ok": verdict == "pass",
        "allowed": verdict == "pass",
        "issues": issues,
        "blockers": blockers,
        "total_credits": total if _is_number(total) else None,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_quote_confirmation(params.get("quote"))
    report_path = out_dir / "quote_confirmation.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_quote_confirmation_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.quote_confirmation_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "quote": {"type": "object"},
                },
                "required": ["quote"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Quote confirmation gate: a cost quote is spendable "
                "only after the user confirms it in their own words; "
                "host popups and prior blanket instructions do not "
                "count. Confirmation semantics reuse spend_brake."
            ),
        )
    )
    return ["qa.quote_confirmation_gate"]


__all__ = [
    "check_quote_confirmation",
    "register_quote_confirmation_gate_capabilities_once",
]
