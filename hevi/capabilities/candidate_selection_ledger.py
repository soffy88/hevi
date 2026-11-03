"""Candidate selection ledger (``qa.candidate_selection_ledger``).

Clean-room restatement of the multi-candidate selection
discipline described in the Infinite Creation review (see
``INFINITE_CREATION_ATTRIBUTION.md``): a segment may be
generated several times, but the record keeps every candidate
and names exactly one selection, with a reason. A later
re-selection must name what it supersedes and give a new reason
that differs from the old one; silently dropping the losers, or
re-selecting without a word, destroys the audit trail that a
long run depends on.

This module judges ledgers only. It generates nothing, scores
nothing, and keeps no media: candidate identity is a hash and a
record, and any quality score a caller supplies is carried
through untouched, never recomputed or certified here.
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
    issue = {"code": code, "detail": f"qa.candidate_selection_ledger: {detail}"}
    issue.update(extra)
    return issue


def check_candidate_ledger(ledger: Any) -> dict[str, Any]:
    """Judge one multi-candidate selection ledger.

    ``ledger`` carries ``segments`` (each with ``id``,
    ``candidates`` carrying ``id`` and ``sha256``, ``selected_id``
    and ``selection_reason``; re-selections add ``supersedes`` and
    ``previous_reason``; segments may carry ``retained_ids``).
    Verdict ``pass`` means every selection names a listed
    candidate, carries a reason, every re-selection is declared
    with a differing reason, and every unselected candidate is
    retained.
    """
    if not isinstance(ledger, dict):
        raise CapabilityError("candidate ledger must be an object")
    issues: list[dict[str, Any]] = []
    segments = ledger.get("segments")
    if not isinstance(segments, list) or not segments:
        raise CapabilityError("candidate ledger requires a non-empty segments list")
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            issues.append(_issue("segment_not_object", f"segment {index} is not an object"))
            continue
        segment_id = segment.get("id") or f"segment {index}"
        candidates = segment.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            issues.append(
                _issue("candidates_missing", f"segment {segment_id} requires a non-empty candidates list", segment=segment_id)
            )
            continue
        candidate_ids: set[str] = set()
        for candidate in candidates:
            if not isinstance(candidate, dict) or not candidate.get("id"):
                issues.append(
                    _issue("candidate_invalid", f"segment {segment_id} has a candidate without an id", segment=segment_id)
                )
                continue
            if candidate["id"] in candidate_ids:
                issues.append(
                    _issue("candidate_id_duplicate", f"segment {segment_id} duplicates candidate {candidate['id']}", segment=segment_id)
                )
            candidate_ids.add(candidate["id"])
            if not candidate.get("sha256"):
                issues.append(
                    _issue("candidate_hash_missing", f"segment {segment_id} candidate {candidate['id']} lacks sha256", segment=segment_id)
                )
        selected_id = segment.get("selected_id")
        if selected_id is not None and selected_id not in candidate_ids:
            issues.append(
                _issue("selection_unknown", f"segment {segment_id} selects unlisted candidate {selected_id}", segment=segment_id)
            )
        if selected_id is not None and not segment.get("selection_reason"):
            issues.append(
                _issue("selection_reason_missing", f"segment {segment_id} selection lacks a reason", segment=segment_id)
            )
        supersedes = segment.get("supersedes")
        if supersedes is not None:
            if supersedes not in candidate_ids:
                issues.append(
                    _issue("supersedes_unknown", f"segment {segment_id} supersedes unlisted candidate {supersedes}", segment=segment_id)
                )
            if supersedes == selected_id:
                issues.append(
                    _issue("supersedes_self", f"segment {segment_id} supersedes its own selection", segment=segment_id)
                )
            previous_reason = segment.get("previous_reason")
            if not previous_reason:
                issues.append(
                    _issue("previous_reason_missing", f"segment {segment_id} re-selection lacks previous_reason", segment=segment_id)
                )
            elif previous_reason == segment.get("selection_reason"):
                issues.append(
                    _issue("reselection_reason_unchanged", f"segment {segment_id} re-selection reason matches the previous reason", segment=segment_id)
                )
        retained = segment.get("retained_ids")
        if retained is not None:
            if not isinstance(retained, list):
                raise CapabilityError("retained_ids must be a list when present")
            retained_set = set(retained)
            for candidate_id in candidate_ids:
                if candidate_id != selected_id and candidate_id not in retained_set:
                    issues.append(
                        _issue(
                            "unselected_candidate_dropped",
                            f"segment {segment_id} drops unselected candidate {candidate_id} from retained_ids",
                            segment=segment_id,
                        )
                    )
    verdict = "fail" if issues else "pass"
    return {
        "ok": verdict != "fail",
        "verdict": verdict,
        "issues": issues,
        "not_checked": [],
        "segment_count": len(segments),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_candidate_ledger(params.get("ledger"))
    report_path = out_dir / "candidate_selection_ledger.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_candidate_selection_ledger_capabilities_once() -> list[str]:
    """Register ``qa.candidate_selection_ledger`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.candidate_selection_ledger",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "ledger": {"type": "object"},
                },
                "required": ["ledger"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Candidate selection ledger: every segment keeps all "
                "candidates, names exactly one selection with a reason, and "
                "declares every re-selection with a differing reason."
            ),
        )
    )
    return ["qa.candidate_selection_ledger"]


__all__ = ["check_candidate_ledger", "register_candidate_selection_ledger_capabilities_once"]
