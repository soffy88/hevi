"""Review sign-off gate (``qa.review_signoff_gate``).

Clean-room rewrite of the method in ``hevi-vs-rain-before-stops.md``
item A3 (from the ``<雨停之前>`` field notes): review feedback
travels a fixed loop -- an external reviewer finds problems, the
author confirms which ones are real and adds their own
observations, the two are merged into one list, the editor acts on
it, and the new cut is re-checked against the *same* list. Two
rules are load-bearing:

1. No unconfirmed opinion enters the fix list. A reviewer's note
   the author has neither confirmed nor rejected is not a task.
2. A re-check re-uses the same checklist, item by item, and the
   previous version is kept -- a new cut that silently drops the
   old one cannot be compared, and a fix that introduces a new
   problem must be caught against the same list.

Author confirmation is never automated away by this gate: the
``author_confirmation`` block must be present and must decide
every feedback item. A missing confirmation fails closed.

This module judges review records only. It never generates, never
calls a model, never touches a budget.
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

_Registered = False


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.review_signoff_gate: {detail}"}
    issue.update(extra)
    return issue


def _as_id_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    if not all(isinstance(item, str) and item.strip() for item in value):
        return None
    return value


def check_review_signoff(review: Any) -> dict[str, Any]:
    """Judge one review record. Returns a report; never raises for a bad record."""
    issues: list[dict[str, Any]] = []
    if not isinstance(review, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "issues": [_issue("review_not_object", "review record must be an object")],
        }
    feedback = review.get("reviewer_feedback")
    if not isinstance(feedback, list) or not feedback:
        issues.append(_issue(
            "feedback_missing",
            "reviewer_feedback must be a non-empty list of feedback items",
        ))
        return {"ok": False, "verdict": "fail", "issues": issues}
    feedback_ids: list[str] = []
    for item in feedback:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip():
            issues.append(_issue(
                "feedback_item_invalid",
                "each feedback item must be an object with a non-empty string id",
            ))
        else:
            feedback_ids.append(item["id"])
    confirmation = review.get("author_confirmation")
    if not isinstance(confirmation, dict):
        issues.append(_issue(
            "author_confirmation_missing",
            "author_confirmation is required: unconfirmed opinions must not enter the fix list",
        ))
        return {"ok": False, "verdict": "fail", "issues": issues}
    confirmed = _as_id_list(confirmation.get("confirmed_ids"))
    rejected = _as_id_list(confirmation.get("rejected_ids"))
    if confirmed is None or rejected is None:
        issues.append(_issue(
            "author_confirmation_invalid",
            "author_confirmation must carry confirmed_ids and rejected_ids string lists",
        ))
        return {"ok": False, "verdict": "fail", "issues": issues}
    decided = set(confirmed) | set(rejected)
    overlap = set(confirmed) & set(rejected)
    if overlap:
        issues.append(_issue(
            "author_confirmation_conflict",
            f"feedback ids decided both ways: {sorted(overlap)}",
            ids=sorted(overlap),
        ))
    undecided = [fid for fid in feedback_ids if fid not in decided]
    if undecided:
        issues.append(_issue(
            "feedback_without_author_decision",
            f"feedback ids with no author decision: {undecided}",
            ids=undecided,
        ))
    fix_list = review.get("fix_list")
    if fix_list is not None:
        fix_ids = _as_id_list(fix_list)
        if fix_ids is None:
            issues.append(_issue(
                "fix_list_invalid", "fix_list must be a list of feedback id strings",
            ))
        else:
            leaked = [fid for fid in fix_ids if fid not in set(confirmed)]
            if leaked:
                issues.append(_issue(
                    "unconfirmed_feedback_in_fix_list",
                    f"fix list contains unconfirmed feedback ids: {leaked}",
                    ids=leaked,
                ))
    recheck = review.get("recheck")
    if recheck is not None:
        if not isinstance(recheck, dict):
            issues.append(_issue("recheck_invalid", "recheck must be an object"))
        else:
            checked = _as_id_list(recheck.get("checked_ids"))
            if checked is None:
                issues.append(_issue(
                    "recheck_invalid", "recheck must carry checked_ids string list",
                ))
            else:
                missing = [fid for fid in (fix_list or confirmed) if fid not in checked]
                if missing:
                    issues.append(_issue(
                        "recheck_missing_item",
                        f"recheck does not cover checklist ids: {missing}",
                        ids=missing,
                    ))
            new_problems = recheck.get("new_problems")
            if new_problems is not None and not isinstance(new_problems, list):
                issues.append(_issue(
                    "recheck_invalid", "recheck.new_problems must be a list when present",
                ))
        if review.get("previous_version_retained") is not True:
            issues.append(_issue(
                "previous_version_not_retained",
                "a recheck requires previous_version_retained=true: keep the old cut",
            ))
    return {
        "ok": not issues,
        "verdict": "pass" if not issues else "fail",
        "issues": issues,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            **_kwargs: Any) -> CapabilityResult:
    report = check_review_signoff(params.get("review"))
    report_path = Path(out_dir) / "review_signoff_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_review_signoff_gate_capabilities_once() -> list[str]:
    """Register ``qa.review_signoff_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.review_signoff_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "review": {"type": "object"},
                },
                "required": ["review"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Review sign-off gate: reviewer feedback needs the "
                "author's explicit confirmation before entering the "
                "fix list, and a re-check re-uses the same checklist "
                "with the previous version kept. Judges records only."
            ),
            line="qa",
        )
    )
    return ["qa.review_signoff_gate"]


register_review_signoff_gate_capabilities_once()
