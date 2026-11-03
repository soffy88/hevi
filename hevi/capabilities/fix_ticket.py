"""Correction ticket schema (``qa.fix_ticket``).

Clean-room rewrite of the *method* in ``hevi-vs-video-workflow-7steps.md``
step 6 ("feedback carries a timecode"): a correction is only
actionable when it can be located. A fix ticket names the timecode,
the segment it belongs to, the check item that failed, and the
verdict in the single ``qa.verdict_vocabulary`` vocabulary. A
``fail`` ticket must also carry an evidence frame -- the frame the
reviewer actually saw -- so the fix can be checked against the
same moment. A ticket without a timecode is refused: "the action
looks wrong" cannot be located, and an unlocatable ticket is not a
correction, it is a comment.

Timecodes are ``MM:SS``, ``MM:SS.s`` or ``HH:MM:SS`` (seconds may
carry one decimal). ``locate_ticket`` places a ticket on a beat
list: the beat whose window contains the ticket's second. A ticket
that lands on no beat is reported unlocatable, not silently
attached to the nearest one.

Verdicts use the single vocabulary only: ``pass`` / ``fail`` /
``not_checked``. Vague conclusions ("looks off", "roughly fine",
"needs work" without a verdict) are refused -- a ticket must say
which of the three it is.
"""

from __future__ import annotations

import json
import re
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

_TIMECODE_RE = re.compile(
    r"^(?:(\d+):)?([0-5]?\d):([0-5]?\d(?:\.\d)?)$")

_VERDICTS = ("pass", "fail", "not_checked")


def parse_timecode(timecode: Any) -> dict[str, Any]:
    """Parse a timecode to seconds. Returns ``{ok, seconds_s, issue}``."""
    if not isinstance(timecode, str) or not timecode.strip():
        return {"ok": False, "seconds_s": None,
                "issue": "timecode must be a non-empty string"}
    match = _TIMECODE_RE.match(timecode.strip())
    if not match:
        return {"ok": False, "seconds_s": None,
                "issue": f"timecode {timecode!r} must be MM:SS, MM:SS.s, "
                         "or HH:MM:SS"}
    hours = int(match.group(1)) if match.group(1) else 0
    minutes = int(match.group(2))
    seconds = float(match.group(3))
    return {"ok": True, "seconds_s": hours * 3600 + minutes * 60 + seconds,
            "issue": None}


def check_fix_ticket(ticket: Any) -> dict[str, Any]:
    """Judge one fix ticket. Returns a report; never raises for a bad ticket."""
    issues: list[dict[str, Any]] = []
    if not isinstance(ticket, dict):
        return {
            "ok": False,
            "verdict": None,
            "seconds_s": None,
            "issues": [{
                "code": "ticket_not_object",
                "detail": "qa.fix_ticket: fix ticket must be an object",
            }],
        }
    parsed = parse_timecode(ticket.get("timecode"))
    if not parsed["ok"]:
        issues.append({
            "code": "bad_timecode",
            "detail": f"qa.fix_ticket: {parsed['issue']}; feedback "
                     "without a timecode cannot be located",
        })
    if not isinstance(ticket.get("segment"), str) \
            or not str(ticket.get("segment", "")).strip():
        issues.append({
            "code": "missing_segment",
            "detail": "qa.fix_ticket: ticket needs a non-empty 'segment' "
                     "(shot/clip id) so the fix lands on one segment",
        })
    if not isinstance(ticket.get("check_item"), str) \
            or not str(ticket.get("check_item", "")).strip():
        issues.append({
            "code": "missing_check_item",
            "detail": "qa.fix_ticket: ticket needs a non-empty "
                     "'check_item' naming the check that failed",
        })
    verdict = ticket.get("verdict")
    if verdict not in _VERDICTS:
        issues.append({
            "code": "bad_verdict",
            "detail": f"qa.fix_ticket: verdict must be one of "
                     f"{', '.join(_VERDICTS)}, not {verdict!r}; vague "
                     "conclusions are refused",
        })
    if verdict == "fail":
        evidence = ticket.get("evidence_frame")
        if not isinstance(evidence, dict):
            issues.append({
                "code": "fail_without_evidence_frame",
                "detail": "qa.fix_ticket: a fail ticket must carry "
                         "'evidence_frame' (the frame the reviewer saw); "
                         "a fail without its frame cannot be re-checked",
            })
        elif "t_s" not in evidence and "frame_no" not in evidence:
            issues.append({
                "code": "evidence_frame_without_position",
                "detail": "qa.fix_ticket: evidence_frame needs 't_s' or "
                         "'frame_no' so the frame can be found again",
            })
    ok = not issues
    return {"ok": ok,
            "verdict": verdict if ok else None,
            "seconds_s": parsed["seconds_s"],
            "issues": issues}


def locate_ticket(
    ticket: dict[str, Any],
    beats: Any,
) -> dict[str, Any]:
    """Place a checked ticket on a beat list. Reports unlocatable honestly."""
    checked = check_fix_ticket(ticket)
    if not checked["ok"]:
        return {"located": False, "beat_index": None,
                "issues": checked["issues"]}
    if not isinstance(beats, list) or not beats:
        return {"located": False, "beat_index": None,
                "issues": [{
                    "code": "beats_missing",
                    "detail": "qa.fix_ticket: locating a ticket needs a "
                             "non-empty beats list",
                }]}
    seconds = checked["seconds_s"]
    assert seconds is not None
    for index, beat in enumerate(beats):
        if not isinstance(beat, dict):
            continue
        start, end = beat.get("t_start_s"), beat.get("t_end_s")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)) \
                and float(start) <= seconds < float(end):
            return {"located": True, "beat_index": index,
                    "beat": beat, "issues": []}
    return {"located": False, "beat_index": None,
            "issues": [{
                "code": "ticket_unlocatable",
                "detail": f"qa.fix_ticket: timecode {ticket.get('timecode')!r} "
                         f"({seconds}s) lands on no beat; the ticket is "
                         "not attached to the nearest beat by guessing",
            }]}


def authorize_fix_ticket(ticket: Any) -> dict[str, Any]:
    """Approve a fix ticket, or refuse it loudly (raises CapabilityError)."""
    report = check_fix_ticket(ticket)
    if not report["ok"]:
        raise CapabilityError(
            "qa.fix_ticket: fix ticket refused: "
            + "; ".join(i["detail"] for i in report["issues"])
        )
    return report


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = authorize_fix_ticket(params.get("ticket"))
    report_path = out_dir / "fix_ticket.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_fix_ticket_capabilities_once() -> list[str]:
    """Register ``qa.fix_ticket`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.fix_ticket",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "ticket": {"type": "object"},
                },
                "required": ["ticket"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Correction ticket: timecode + segment + check item + "
                "three-state verdict, with an evidence frame required "
                "on fail tickets. A ticket without a timecode, or with "
                "a vague conclusion, is refused. Locating places a "
                "ticket on the beat whose window contains its second; "
                "an unlocatable ticket is reported, never guessed onto "
                "the nearest beat."
            ),
            line="qa",
        )
    )
    return ["qa.fix_ticket"]


register_fix_ticket_capabilities_once()
