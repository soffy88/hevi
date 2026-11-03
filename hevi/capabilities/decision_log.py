"""DECISION log (``qa.decision_log``).

Clean-room rewrite of the *method* of the DECISION log in
``win4r/video-director`` (MIT; see VIDEO_DIRECTOR_ATTRIBUTION.md):
in autonomous mode every creative call the builder makes on its
own authority is recorded with its reason, so the delivery can
be audited and any single call can be overturned without
rewriting history. No text, code or script from the source
repository is copied here.

A log is an append-only list of entries. An entry records a
``decision`` and the ``reason`` for it; ``alternatives`` it was
chosen over, the ``shot_id`` / ``film`` it belongs to, and
whether it is ``reversible`` travel with it. Overturning an
entry never deletes or edits it: ``overturn_decision`` marks
the original ``overturned_by`` the id of the superseding entry
and records the overturn reason on the superseding entry, so
both the call and its reversal stay in the record. An entry
id that is reused, an overturn of an unknown id, or an
overturn whose superseding entry does not exist in the log
raises -- a log that cannot say what happened is worse than
no log.

This module judges records only. It never decides anything
itself and never modifies a film, a timeline or a render.
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


def new_log() -> list[dict[str, Any]]:
    """An empty decision log."""
    return []


def record_decision(
    log: list[dict[str, Any]], entry: dict[str, Any]
) -> dict[str, Any]:
    """Append one entry to ``log`` (in place) and return it.

    ``decision`` and ``reason`` are required and must be
    non-empty strings. ``id`` defaults to ``D<n>`` (one past
    the highest existing ``D<n>`` id); reusing an existing id
    raises. The returned entry always carries
    ``overturned_by: None`` until it is overturned.
    """
    if not isinstance(log, list):
        raise CapabilityError("qa.decision_log: log must be a list")
    if not isinstance(entry, dict):
        raise CapabilityError("qa.decision_log: entry must be an object (dict)")
    decision = entry.get("decision")
    reason = entry.get("reason")
    if not isinstance(decision, str) or not decision.strip():
        raise CapabilityError("qa.decision_log: entry needs a non-empty decision")
    if not isinstance(reason, str) or not reason.strip():
        raise CapabilityError("qa.decision_log: entry needs a non-empty reason")
    existing_ids = {e.get("id") for e in log if isinstance(e, dict)}
    entry_id = entry.get("id")
    if entry_id is None:
        taken = [int(str(i)[1:]) for i in existing_ids
                 if isinstance(i, str) and i.startswith("D") and i[1:].isdigit()]
        entry_id = f"D{max(taken, default=0) + 1}"
    elif not isinstance(entry_id, str) or not entry_id.strip():
        raise CapabilityError("qa.decision_log: entry id must be a non-empty string")
    elif entry_id in existing_ids:
        raise CapabilityError(f"qa.decision_log: duplicate entry id: {entry_id!r}")
    alternatives = entry.get("alternatives", [])
    if not isinstance(alternatives, list):
        raise CapabilityError("qa.decision_log: alternatives must be a list")
    recorded = {
        "id": entry_id,
        "decision": decision.strip(),
        "reason": reason.strip(),
        "alternatives": list(alternatives),
        "shot_id": entry.get("shot_id"),
        "film": entry.get("film"),
        "reversible": bool(entry.get("reversible", True)),
        "overturned_by": None,
        "overturn_reason": None,
    }
    log.append(recorded)
    return recorded


def overturn_decision(
    log: list[dict[str, Any]],
    entry_id: str,
    *,
    superseding_id: str,
    reason: str,
) -> dict[str, Any]:
    """Mark ``entry_id`` overturned by ``superseding_id``.

    Both entries must already be in the log, the original must
    not already be overturned, and ``reason`` must be non-empty.
    The original entry is annotated, never removed or rewritten.
    """
    if not isinstance(log, list):
        raise CapabilityError("qa.decision_log: log must be a list")
    if not isinstance(reason, str) or not reason.strip():
        raise CapabilityError("qa.decision_log: overturn needs a non-empty reason")
    by_id = {e.get("id"): e for e in log if isinstance(e, dict)}
    original = by_id.get(entry_id)
    if original is None:
        raise CapabilityError(f"qa.decision_log: unknown entry id: {entry_id!r}")
    if superseding_id not in by_id:
        raise CapabilityError(
            f"qa.decision_log: superseding entry not in log: {superseding_id!r}")
    if superseding_id == entry_id:
        raise CapabilityError("qa.decision_log: an entry cannot overturn itself")
    if original.get("overturned_by") is not None:
        raise CapabilityError(
            f"qa.decision_log: entry {entry_id!r} is already overturned "
            f"by {original['overturned_by']!r}")
    original["overturned_by"] = superseding_id
    original["overturn_reason"] = reason.strip()
    superseding = by_id[superseding_id]
    overturns = superseding.setdefault("overturns", [])
    overturns.append({"overturned": entry_id, "reason": reason.strip()})
    return original


def decision_log_report(log: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise a log: counts, standing decisions, overturned ones.

    The report verdict is ``"pass"`` when every entry is
    well-formed (decision + reason present); malformed entries
    are listed and fail the report. Overturned decisions are
    reported, not hidden: standing decisions are the log minus
    the overturned ones.
    """
    if not isinstance(log, list):
        raise CapabilityError("qa.decision_log: log must be a list")
    problems: list[str] = []
    seen: set[Any] = set()
    for idx, entry in enumerate(log):
        if not isinstance(entry, dict):
            problems.append(f"entry[{idx}] is not an object")
            continue
        if entry.get("id") in seen:
            problems.append(f"duplicate id: {entry.get('id')!r}")
        seen.add(entry.get("id"))
        if not isinstance(entry.get("decision"), str) or not entry["decision"].strip():
            problems.append(f"entry[{idx}] has no decision")
        if not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
            problems.append(f"entry[{idx}] has no reason")
    overturned = [e for e in log if isinstance(e, dict) and e.get("overturned_by")]
    standing = [e for e in log if isinstance(e, dict) and not e.get("overturned_by")]
    return {
        "capability": "qa.decision_log",
        "verdict": "fail" if problems else "pass",
        "problems": problems,
        "entry_count": len(log),
        "standing_count": len(standing),
        "overturned_count": len(overturned),
        "standing_ids": [e.get("id") for e in standing],
        "overturned": [
            {"id": e.get("id"), "overturned_by": e.get("overturned_by"),
             "overturn_reason": e.get("overturn_reason")}
            for e in overturned
        ],
        "entries": list(log),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    entries = params.get("entries", [])
    if not isinstance(entries, list):
        raise CapabilityError("qa.decision_log: entries must be a list")
    log = new_log()
    for entry in entries:
        record_decision(log, entry)
    for overturn in params.get("overturns", []) or []:
        if not isinstance(overturn, dict):
            raise CapabilityError("qa.decision_log: overturn must be an object")
        overturn_decision(
            log, overturn["entry_id"],
            superseding_id=overturn["superseding_id"],
            reason=overturn["reason"])
    report = decision_log_report(log)
    report_path = out_dir / "decision_log_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "verdict": report["verdict"],
            "pass": report["verdict"] == "pass",
            "entry_count": report["entry_count"],
            "overturned_count": report["overturned_count"],
        },
    )


def register_decision_log_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.decision_log",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "entries": {"type": "array", "items": {"type": "object"}},
                    "overturns": {"type": "array", "items": {"type": "object"}},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "DECISION log: every autonomous creative call recorded "
                "with its reason and the alternatives it beat, "
                "append-only; overturning marks the original as "
                "overturned by a superseding entry and never deletes "
                "or rewrites it. Records only; decides nothing."
            ),
            line="qa",
        )
    )
    return ["qa.decision_log"]


register_decision_log_capabilities_once()
