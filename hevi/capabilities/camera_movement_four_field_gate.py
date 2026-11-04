"""Camera movement four-field gate (``qa.camera_movement_four_field_gate``).

Clean-room discipline gate only. Every movement entry in the single
source ``cinematic_data/camera_movements.json`` must carry all four
fields of the movement template, each non-empty: Movement (what the
camera or lens physically does), Speed (how fast and how steady),
Framing (what stays in frame and where), End (the landing
composition). An entry missing or blanking any field fails; this
gate judges the catalogue only and renders nothing. No site prompt
text is copied here. See CAMERA_MOVEMENTS_ATTRIBUTION.md.
"""

from __future__ import annotations

import json
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

FOUR_FIELDS = ("movement", "speed", "framing", "end")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_four_fields(entry: Any) -> dict[str, Any]:
    """Validate one movement entry. Returns a report; never raises."""
    issues: list[dict[str, Any]] = []
    label = "entry"
    if not isinstance(entry, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("entry_not_object", "each movement must be an object")],
            "id": None,
        }
    label = str(entry.get("id", "entry"))
    for field in FOUR_FIELDS:
        value = entry.get(field)
        if value is None:
            issues.append(
                _issue(
                    f"{label}:field_missing:{field}",
                    f"movement {label!r} is missing field {field!r}",
                )
            )
        elif not str(value).strip():
            issues.append(
                _issue(
                    f"{label}:field_blank:{field}",
                    f"movement {label!r} has a blank field {field!r}",
                )
            )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "id": entry.get("id"),
    }


def check_movement_four_fields(
    entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate every entry of the catalogue. Returns a report."""
    rows = entries if entries is not None else load_movements()
    issues: list[dict[str, Any]] = []
    checked = 0
    for entry in rows:
        report = check_four_fields(entry)
        checked += 1
        issues.extend(report["issues"])
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "checked": checked,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    entry = params.get("entry")
    if isinstance(entry, dict):
        report: dict[str, Any] = check_four_fields(entry)
    else:
        entries = params.get("entries")
        report = check_movement_four_fields(
            list(entries) if isinstance(entries, list) else None
        )
    report_path = out_dir / "camera_movement_four_field.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_camera_movement_four_field_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.camera_movement_four_field_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "entry": {"type": "object"},
                    "entries": {"type": "array", "items": {"type": "object"}},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Camera movement four-field gate: every movement "
                "entry must carry non-empty Movement, Speed, Framing "
                "and End fields; any missing or blank field fails."
            ),
        )
    )
    return ["qa.camera_movement_four_field_gate"]


__all__ = [
    "FOUR_FIELDS",
    "check_four_fields",
    "check_movement_four_fields",
    "register_camera_movement_four_field_gate_capabilities_once",
]
