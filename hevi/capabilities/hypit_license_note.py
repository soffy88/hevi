"""Hypit licence note (``qa.hypit_license_note``).

Reference notes only. The reviewed upstream project is
released under a modified Apache License 2.0: personal and
single-tenant use is free, but multi-tenant / software-as-a-
service use and commercial redistribution need a separate
commercial authorisation, and the project's name, logo, and
copyright notices must not be removed from the command-line
tool, reports, or manifests. Outputs belong to the user.
These notes record that position in our own words for
downstream gates to cite; they grant nothing and they are
not legal advice. Calling the licence MIT, or claiming
unrestricted commercial use, fails the note check. See
HYPIT_ATTRIBUTION.md.
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

_Registered = False

_REQUIRED_FIELDS = (
    "license",
    "multi_tenant_restriction",
    "redistribution_restriction",
    "attribution_retention",
)


def _issue(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def hypit_license_notes() -> list[dict[str, str]]:
    """Return the licence position notes, in our own words."""
    return [
        {
            "license": "Modified Apache License 2.0",
            "multi_tenant_restriction": (
                "Multi-tenant and software-as-a-service use needs a "
                "separate commercial authorisation."
            ),
            "redistribution_restriction": (
                "Commercial redistribution needs a separate commercial authorisation."
            ),
            "attribution_retention": (
                "The project name, logo, and copyright notices must not "
                "be removed from the tool, reports, or manifests."
            ),
            "outputs": "Outputs produced with the tool belong to the user.",
            "scope": (
                "This note records the upstream position for citation; "
                "it grants nothing and is not legal advice."
            ),
        }
    ]


def check_license_note(note: Any) -> dict[str, Any]:
    """Check a caller-supplied licence note for completeness.

    Returns a report dict with ``verdict`` pass/fail, ``ok``,
    and ``issues``. A note missing any required restriction,
    calling the licence MIT, or claiming unrestricted
    commercial use all fail.
    """
    issues: list[dict[str, str]] = []
    if not isinstance(note, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("note_not_object", "note must be a JSON object")],
        }
    for field in _REQUIRED_FIELDS:
        value = note.get(field)
        if not isinstance(value, str) or not value.strip():
            issues.append(_issue(f"{field}_missing", f"note must carry a non-empty {field}"))
    license_text = note.get("license")
    if isinstance(license_text, str) and "mit" in license_text.lower():
        issues.append(
            _issue(
                "license_misnamed",
                "the upstream licence is a modified Apache License 2.0, not MIT",
            )
        )
    if note.get("commercial_use_unrestricted") is True:
        issues.append(
            _issue(
                "unrestricted_commercial_claim",
                "commercial use is not unrestricted: multi-tenant and "
                "redistribution use need commercial authorisation",
            )
        )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_license_note(params.get("note", hypit_license_notes()[0]))
    report_path = out_dir / "hypit_license_note.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_hypit_license_note_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.hypit_license_note",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "note": {"type": "object"},
                },
                "required": [],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Hypit licence note (reference only): modified Apache "
                "License 2.0; multi-tenant/SaaS and commercial "
                "redistribution need commercial authorisation; name, "
                "logo, and copyright notices must be retained."
            ),
        )
    )
    return ["qa.hypit_license_note"]


__all__ = [
    "check_license_note",
    "hypit_license_notes",
    "register_hypit_license_note_capabilities_once",
]
