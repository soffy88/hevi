"""First-segment confirmation gate (``qa.first_segment_confirmation_gate``).

Clean-room rewrite of the discipline in ``hevi-vs-digital-human-koubo-recheck.md``
item A1: before any batch generation, the first segment is produced
on its own and confirmed, and only then may the batch proceed. A
batch that starts without a confirmed first segment fails closed.

The confirmation record must name the segment, the confirmer, and
the time, and its decision must be exactly ``confirmed``. The
two-party sign-off discipline is reused, not re-invented: the
record must carry a ``review_signoff`` block that passes
``qa.review_signoff_gate`` (reviewer feedback decided item by item
by the author, unconfirmed opinions never entering the fix list).
A confirmation for the wrong segment, a pending decision, or a
missing dual sign-off is not a confirmation.

A retake re-opens the quote: a plan that retakes the first segment
without a fresh quote (``requoted``) fails. This module judges
records only. It never generates, never calls a model, and never
touches a budget.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)
from hevi.capabilities.review_signoff_gate import check_review_signoff

_Registered = False


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.first_segment_confirmation_gate: {detail}"}
    issue.update(extra)
    return issue


def _parse_time(value: Any) -> dict[str, Any]:
    """Parse an ISO-8601 time. Returns ``{ok, epoch_s, issue}``."""
    if not isinstance(value, str) or not value.strip():
        return {"ok": False, "epoch_s": None,
                "issue": "time must be a non-empty ISO-8601 string"}
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return {"ok": False, "epoch_s": None,
                "issue": f"time {value!r} is not ISO-8601"}
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return {"ok": True, "epoch_s": moment.timestamp(), "issue": None}


def check_first_segment_confirmation(plan: Any) -> dict[str, Any]:
    """Judge one batch plan. Returns a report; never raises for a bad plan. Composes (3O SPEC 1.2): check_review_signoff."""
    issues: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "first_segment_id": None,
            "batch_may_proceed": False,
            "issues": [_issue("plan_not_object", "batch plan must be an object")],
        }
    segments = plan.get("segments")
    first_id: str | None = None
    if not isinstance(segments, list) or not segments:
        issues.append(_issue(
            "segments_missing",
            "segments must be a non-empty list of segment ids",
        ))
    else:
        bad = [s for s in segments if not isinstance(s, str) or not s.strip()]
        if bad:
            issues.append(_issue(
                "segment_id_invalid",
                "every segment id must be a non-empty string",
            ))
        if len(set(segments)) != len(segments):
            issues.append(_issue(
                "segment_id_duplicate",
                "segment ids must be unique within a batch",
            ))
        if isinstance(segments[0], str) and segments[0].strip():
            first_id = segments[0]
    batch_started = plan.get("batch_started") is True
    batch_requested = plan.get("batch_requested") is True
    batch_active = batch_started or batch_requested

    confirmation = plan.get("first_segment_confirmation")
    if confirmation is None:
        issues.append(_issue(
            "first_segment_confirmation_missing",
            "the first segment must be confirmed before batch generation",
        ))
    elif not isinstance(confirmation, dict):
        issues.append(_issue(
            "first_segment_confirmation_invalid",
            "first_segment_confirmation must be an object",
        ))
    else:
        if confirmation.get("segment_id") != first_id:
            issues.append(_issue(
                "confirmation_wrong_segment",
                "confirmation must name the first segment "
                f"({first_id!r}), not {confirmation.get('segment_id')!r}",
                segment_id=confirmation.get("segment_id"),
            ))
        if not isinstance(confirmation.get("confirmer"), str) \
                or not confirmation["confirmer"].strip():
            issues.append(_issue(
                "confirmer_missing",
                "confirmation must name the confirmer",
            ))
        parsed = _parse_time(confirmation.get("confirmed_at"))
        if not parsed["ok"]:
            issues.append(_issue(
                "confirmed_at_invalid",
                f"confirmation must carry a valid confirmed_at time: {parsed['issue']}",
            ))
        if confirmation.get("decision") != "confirmed":
            issues.append(_issue(
                "confirmation_not_confirmed",
                "confirmation decision must be exactly 'confirmed'; "
                "a pending or rejected first segment never opens the batch",
            ))
        signoff = confirmation.get("review_signoff")
        if not isinstance(signoff, dict):
            issues.append(_issue(
                "dual_signoff_missing",
                "confirmation must carry a review_signoff block judged "
                "by the qa.review_signoff_gate dual-signoff discipline",
            ))
        else:
            result = check_review_signoff(signoff)
            if not result["ok"]:
                issues.append(_issue(
                    "dual_signoff_failed",
                    "review_signoff block does not pass "
                    "qa.review_signoff_gate",
                    signoff_issues=result["issues"],
                ))
    if batch_active and any(
        i["code"] in (
            "first_segment_confirmation_missing",
            "first_segment_confirmation_invalid",
            "confirmation_wrong_segment",
            "confirmation_not_confirmed",
            "dual_signoff_missing",
            "dual_signoff_failed",
        )
        for i in issues
    ):
        issues.append(_issue(
            "batch_without_first_segment_confirmation",
            "batch generation without a confirmed first segment is refused",
        ))
    if plan.get("retake") is True and plan.get("requoted") is not True:
        issues.append(_issue(
            "retake_without_requote",
            "a retake of the first segment requires a fresh quote "
            "(requoted=true) before the batch proceeds",
        ))
    verdict = "pass" if not issues else "fail"
    return {
        "ok": not issues,
        "verdict": verdict,
        "first_segment_id": first_id,
        "batch_may_proceed": verdict == "pass",
        "issues": issues,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            **_kwargs: Any) -> CapabilityResult:
    report = check_first_segment_confirmation(params.get("plan"))
    report_path = Path(out_dir) / "first_segment_confirmation_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_first_segment_confirmation_gate_capabilities_once() -> list[str]:
    """Register ``qa.first_segment_confirmation_gate`` (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.first_segment_confirmation_gate",
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
                "First-segment confirmation gate: the first segment "
                "must be produced and confirmed (segment id, confirmer, "
                "time, dual sign-off per qa.review_signoff_gate) before "
                "any batch generation; a retake needs a fresh quote. "
                "Judges records only."
            ),
            line="qa",
        )
    )
    return ["qa.first_segment_confirmation_gate"]


register_first_segment_confirmation_gate_capabilities_once()
