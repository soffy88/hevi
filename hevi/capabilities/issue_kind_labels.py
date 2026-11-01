"""Feedback-list kind labels (``qa.issue_kind_labels``).

Clean-room rewrite of the method in ``hevi-vs-rain-before-stops.md``
item A4 (from the ``<雨停之前>`` field notes): a merged feedback
list must separate three kinds of item, because they are acted on
differently:

- ``continuity``: a definite break (a prop changed, a move
  unaccounted for) -- must be fixed.
- ``aesthetic``: a judgement call (pacing, taste) -- the author
  decides; an aesthetic note must never be executed as if it were
  a continuity break, i.e. it must not be scheduled with
  ``must_fix`` priority.
- ``unconfirmed``: a suspicion not yet verified -- it never counts
  as passed, and it never counts as fixed, until it is verified
  and re-labelled.

Verdicts stay in the single ``qa.verdict_vocabulary`` vocabulary
(``pass`` / ``fail`` / ``not_checked``); this module only adds the
kind label and the counting rules. It validates ``fix_ticket``-
shaped records without modifying ``qa.fix_ticket`` itself.

This module judges records only. It never generates, never calls a
model, never touches a budget.
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
from hevi.capabilities.verdict_vocabulary import normalise_verdict

_Registered = False

ISSUE_KINDS = ("continuity", "aesthetic", "unconfirmed")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.issue_kind_labels: {detail}"}
    issue.update(extra)
    return issue


def check_issue_kind(item: Any) -> dict[str, Any]:
    """Judge one labelled feedback item. Never raises for a bad item."""
    issues: list[dict[str, Any]] = []
    if not isinstance(item, dict):
        return {
            "ok": False,
            "verdict": None,
            "kind": None,
            "issues": [_issue("item_not_object", "feedback item must be an object")],
        }
    kind = item.get("issue_kind")
    if kind not in ISSUE_KINDS:
        issues.append(_issue(
            "issue_kind_missing",
            f"issue_kind must be one of {list(ISSUE_KINDS)}",
            issue_kind=kind,
        ))
    if "verdict" not in item:
        verdict = None
        issues.append(_issue(
            "verdict_invalid",
            "verdict is required and must be pass/fail/not_checked in the single vocabulary",
        ))
    else:
        try:
            verdict = normalise_verdict(item.get("verdict"))
        except CapabilityError:
            verdict = None
            issues.append(_issue(
                "verdict_invalid",
                "verdict must be pass/fail/not_checked in the single vocabulary",
                verdict=item.get("verdict"),
            ))
    if kind == "aesthetic" and item.get("execution_priority") == "must_fix":
        issues.append(_issue(
            "aesthetic_executed_as_continuity",
            "an aesthetic suggestion must not be scheduled as must_fix; "
            "the author decides, it is not a continuity break",
        ))
    if kind == "unconfirmed" and verdict == "pass":
        issues.append(_issue(
            "unconfirmed_counted_as_pass",
            "an unconfirmed suspicion never counts as pass until verified and re-labelled",
        ))
    return {
        "ok": not issues,
        "verdict": verdict,
        "kind": kind if kind in ISSUE_KINDS else None,
        "issues": issues,
    }


def summarise_labelled(items: Any) -> dict[str, Any]:
    """Summarise a labelled list. Unconfirmed items never count as passed or fixed."""
    issues: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return {
            "ok": False,
            "counts": {},
            "passed": 0,
            "issues": [_issue("items_not_list", "labelled feedback must be a list")],
        }
    counts = {kind: 0 for kind in ISSUE_KINDS}
    passed = 0
    for item in items:
        checked = check_issue_kind(item)
        issues.extend(checked["issues"])
        if checked["kind"] is not None:
            counts[checked["kind"]] += 1
        # Only a verified (non-unconfirmed) pass counts.
        if checked["verdict"] == "pass" and checked["kind"] in ("continuity", "aesthetic"):
            passed += 1
    return {
        "ok": not issues,
        "counts": counts,
        "passed": passed,
        "total": len(items),
        "issues": issues,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            **_kwargs: Any) -> CapabilityResult:
    items = params.get("items")
    if isinstance(items, list) and len(items) == 1:
        report = check_issue_kind(items[0])
    else:
        report = summarise_labelled(items)
    report_path = Path(out_dir) / "issue_kind_labels_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path),
            "verdict": "pass" if report["ok"] else "fail"},
    )


def register_issue_kind_labels_capabilities_once() -> list[str]:
    """Register ``qa.issue_kind_labels`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.issue_kind_labels",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "items": {"type": "array"},
                },
                "required": ["items"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Feedback kind labels: every list item must be "
                "continuity, aesthetic or unconfirmed; aesthetic "
                "notes must not be executed as continuity breaks, "
                "and unconfirmed suspicions never count as passed. "
                "Judges records only."
            ),
            line="qa",
        )
    )
    return ["qa.issue_kind_labels"]


register_issue_kind_labels_capabilities_once()
