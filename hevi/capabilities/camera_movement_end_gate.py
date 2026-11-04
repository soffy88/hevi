"""Camera movement landing gate (``qa.camera_movement_end_gate``).

Clean-room discipline gate only. Every movement clause must declare
its landing: the End field of a catalogue entry must be present and
non-empty, and a free-text movement clause must carry an ``End:``
segment followed by non-empty landing text. A clause with no landing
declaration fails; this gate judges the clause only and renders
nothing. No site prompt text is copied here. See
CAMERA_MOVEMENTS_ATTRIBUTION.md.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from hevi.capabilities.cinematic_techniques import load_movements
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

_END_MARKER = re.compile(r"(?i)\bend\s*:")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _check_clause_text(text: str) -> list[dict[str, Any]]:
    match = _END_MARKER.search(text or "")
    if match is None:
        return [
            _issue(
                "end_marker_missing",
                "movement clause carries no 'End:' landing declaration",
            )
        ]
    if not text[match.end():].strip():
        return [
            _issue(
                "end_blank",
                "movement clause 'End:' segment has no landing text",
            )
        ]
    return []


def check_movement_end(subject: Any) -> dict[str, Any]:
    """Validate the landing declaration. Returns a report; never raises.

    Accepts a catalogue-style entry (``{"id", "end", ...}``), a clause
    dict (``{"clause": "... End: ..."}``), or a plain clause string.
    """
    issues: list[dict[str, Any]] = []
    movement_id: Any = None
    if isinstance(subject, dict):
        movement_id = subject.get("id")
        if "end" in subject:
            end = subject.get("end")
            if end is None:
                issues.append(
                    _issue("end_missing", "movement entry declares no End field")
                )
            elif not str(end).strip():
                issues.append(
                    _issue("end_blank", "movement entry End field is blank")
                )
        elif isinstance(subject.get("clause"), str):
            issues.extend(_check_clause_text(subject["clause"]))
        else:
            issues.append(
                _issue(
                    "end_missing",
                    "movement clause declares neither an End field "
                    "nor a clause text carrying 'End:'",
                )
            )
    elif isinstance(subject, str):
        issues.extend(_check_clause_text(subject))
    else:
        issues.append(
            _issue(
                "subject_not_object_or_text",
                "landing check needs a movement entry, a clause dict, "
                "or a clause string",
            )
        )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "id": movement_id,
    }


def check_all_movement_ends(
    entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate the End field of every catalogue entry."""
    rows = entries if entries is not None else load_movements()
    issues: list[dict[str, Any]] = []
    for entry in rows:
        issues.extend(check_movement_end(entry)["issues"])
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "checked": len(rows),
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    subject = params.get("entry", params.get("clause"))
    if subject is None:
        report: dict[str, Any] = check_all_movement_ends()
    else:
        report = check_movement_end(subject)
    report_path = out_dir / "camera_movement_end.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_camera_movement_end_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.camera_movement_end_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "entry": {"type": "object"},
                    "clause": {"type": "string"},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Camera movement landing gate: every movement entry "
                "or clause must declare a non-empty End landing; a "
                "clause without an 'End:' landing declaration fails."
            ),
        )
    )
    return ["qa.camera_movement_end_gate"]


__all__ = [
    "check_movement_end",
    "check_all_movement_ends",
    "register_camera_movement_end_gate_capabilities_once",
]
