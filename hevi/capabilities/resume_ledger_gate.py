"""Resume ledger gate (``qa.resume_ledger_gate``).

Clean-room restatement of the resumable-run discipline described
in the Infinite Creation review (see
``INFINITE_CREATION_ATTRIBUTION.md``): a long run is a ledger of
segments, and resuming must be idempotent. A finished segment
carries its artifact hash and completion record; a resume plan
never regenerates a finished segment without an explicit force
flag and a reason; a segment with several candidates names
exactly one selected candidate, and the selection is recorded.
Re-running the same ledger against the same plan always yields
the same verdict: the ledger holds no hidden state and performs
no generation itself.

This module judges ledgers only. It never generates, never calls
a model, never touches a queue, and never touches a budget.
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

_STATUSES = ("done", "pending", "failed", "running")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.resume_ledger_gate: {detail}"}
    issue.update(extra)
    return issue


def check_resume_ledger(ledger: Any) -> dict[str, Any]:
    """Judge one resumable-run ledger against a resume plan.

    ``ledger`` carries ``segments`` (each with ``id``, ``status``,
    and, when done, ``artifact_sha`` and ``completed_at``; segments
    may carry ``candidates``) and ``plan`` (segment ids to
    generate, plus optional ``force`` entries with ``segment_id``
    and ``reason``). Verdict ``pass`` means finished segments are
    evidenced, the plan skips finished segments unless forced with
    a reason, and every segment names at most one selected
    candidate, exactly one when done.
    """
    if not isinstance(ledger, dict):
        raise CapabilityError("resume ledger must be an object")
    issues: list[dict[str, Any]] = []
    segments = ledger.get("segments")
    if not isinstance(segments, list) or not segments:
        raise CapabilityError("resume ledger requires a non-empty segments list")
    segment_by_id: dict[str, dict[str, Any]] = {}
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            issues.append(_issue("segment_not_object", f"segment {index} is not an object"))
            continue
        segment_id = segment.get("id")
        if not segment_id:
            issues.append(_issue("segment_id_missing", f"segment {index} lacks an id"))
            continue
        if segment_id in segment_by_id:
            issues.append(_issue("segment_id_duplicate", f"segment id {segment_id} is duplicated"))
        segment_by_id[segment_id] = segment
        status = segment.get("status")
        if status not in _STATUSES:
            issues.append(
                _issue(
                    "status_invalid",
                    f"segment {segment_id} status must be one of {_STATUSES}",
                    segment=segment_id,
                )
            )
        if status == "done":
            if not segment.get("artifact_sha"):
                issues.append(
                    _issue("done_segment_unevidenced", f"done segment {segment_id} lacks artifact_sha", segment=segment_id)
                )
            if not segment.get("completed_at"):
                issues.append(
                    _issue("done_segment_unevidenced", f"done segment {segment_id} lacks completed_at", segment=segment_id)
                )
        candidates = segment.get("candidates", [])
        if not isinstance(candidates, list):
            raise CapabilityError("candidates must be a list when present")
        candidate_ids = set()
        selected = []
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
            if candidate.get("selected"):
                selected.append(candidate["id"])
        if len(selected) > 1:
            issues.append(
                _issue("multiple_selected", f"segment {segment_id} selects {len(selected)} candidates", segment=segment_id)
            )
        if status == "done" and len(selected) != 1:
            issues.append(
                _issue("done_segment_unselected", f"done segment {segment_id} must select exactly one candidate", segment=segment_id)
            )
    plan = ledger.get("plan", {})
    if not isinstance(plan, dict):
        raise CapabilityError("plan must be an object when present")
    generate = plan.get("generate", [])
    if not isinstance(generate, list):
        raise CapabilityError("plan.generate must be a list when present")
    force_entries = plan.get("force", [])
    if not isinstance(force_entries, list):
        raise CapabilityError("plan.force must be a list when present")
    forced: dict[str, str] = {}
    for entry in force_entries:
        if not isinstance(entry, dict) or not entry.get("segment_id"):
            issues.append(_issue("force_entry_invalid", "force entry requires segment_id"))
            continue
        if not entry.get("reason"):
            issues.append(
                _issue("force_without_reason", f"force for {entry['segment_id']} lacks a reason", segment=entry["segment_id"])
            )
        forced[entry["segment_id"]] = entry.get("reason", "")
    for segment_id in generate:
        segment = segment_by_id.get(segment_id)
        if segment is None:
            issues.append(_issue("plan_segment_unknown", f"plan names unknown segment {segment_id}"))
            continue
        if segment.get("status") == "done" and segment_id not in forced:
            issues.append(
                _issue(
                    "regenerate_done_without_force",
                    f"plan regenerates done segment {segment_id} without a force entry",
                    segment=segment_id,
                )
            )
    verdict = "fail" if issues else "pass"
    done_count = sum(1 for s in segment_by_id.values() if s.get("status") == "done")
    return {
        "ok": verdict != "fail",
        "verdict": verdict,
        "issues": issues,
        "not_checked": [],
        "segment_count": len(segment_by_id),
        "done_count": done_count,
        "planned_count": len(generate),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_resume_ledger(params.get("ledger"))
    report_path = out_dir / "resume_ledger.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_resume_ledger_gate_capabilities_once() -> list[str]:
    """Register ``qa.resume_ledger_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.resume_ledger_gate",
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
                "Resume ledger gate: finished segments must be evidenced, a "
                "resume plan must skip them unless forced with a reason, and "
                "every segment must name at most one selected candidate."
            ),
        )
    )
    return ["qa.resume_ledger_gate"]


__all__ = ["check_resume_ledger", "register_resume_ledger_gate_capabilities_once"]
