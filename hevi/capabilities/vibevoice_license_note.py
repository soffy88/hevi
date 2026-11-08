"""VibeVoice license note (``qa.vibevoice_license_note``).

Clean-room restatement of the VibeVoice review (see
``VIBEVOICE_ATTRIBUTION.md``): the code is MIT-licensed
(Copyright 2025 Microsoft), but the repository says nothing
about the weight license; the model-hub card data marks the
weights MIT while its top-level license field is None. The
three statements must never be merged into one claim, and
the project's research-only warning ("research purposes
only, commercial use not recommended") must ride along with
any commercial-use mention. This module records the note
only; it executes nothing.
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

CODE_LICENSE = "MIT"
CODE_LICENSE_HOLDER = "Microsoft (2025)"
WEIGHT_LICENSE = "MIT"
WEIGHT_LICENSE_SOURCE = "huggingface_card"
REPO_WEIGHT_LICENSE = "not_stated"
COMMERCIAL_USE = "research_only"


def vibevoice_license_notes() -> dict[str, Any]:
    """Return the recorded VibeVoice license note (three-way split)."""
    return {
        "code_license": CODE_LICENSE,
        "code_license_holder": CODE_LICENSE_HOLDER,
        "weight_license": WEIGHT_LICENSE,
        "weight_license_source": WEIGHT_LICENSE_SOURCE,
        "repo_weight_license": REPO_WEIGHT_LICENSE,
        "commercial_use": COMMERCIAL_USE,
        "research_only_warning": (
            "research purposes only; commercial use is not recommended by the project"
        ),
        "executed_here": False,
    }


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_vibevoice_license_note(note: Any) -> dict[str, Any]:
    """Validate a VibeVoice license note.

    Verdicts are ``pass`` / ``fail`` only. The code license
    must be MIT; the weight license must be cited from the
    model-hub card, never from the repository (which states
    nothing about weights); a claim that one MIT covers both
    code and weights fails; and any commercial-use mention
    without the research-only warning fails.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(note, dict):
        return fail(
            "note_not_object",
            "vibevoice license note must be a JSON object",
        )
    if note.get("code_license") != CODE_LICENSE:
        return fail(
            "code_license_mismatch",
            "VibeVoice code license is MIT",
        )
    if note.get("mit_covers_weights") is True:
        return fail(
            "weight_license_mixed",
            "one MIT must never be claimed to cover both code "
            "and weights; the weight license is a separate "
            "model-hub card statement",
        )
    if note.get("weight_license_source") == "repository":
        return fail(
            "weight_license_mixed",
            "the repository states no weight license; the weight "
            "license is cited from the model-hub card only",
        )
    repo_statement = note.get("repo_weight_license")
    if repo_statement is not None and repo_statement != REPO_WEIGHT_LICENSE:
        return fail(
            "repo_weight_license_misstated",
            "the repository states no weight license",
        )
    if note.get("commercial_use") == "commercial" and note.get("research_only_warning") is not True:
        return fail(
            "commercial_without_research_warning",
            "any commercial-use mention must carry the project's research-only warning",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_vibevoice_license_note(params.get("note"))
    report_path = out_dir / "vibevoice_license_note_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_vibevoice_license_note_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.vibevoice_license_note",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "note": {"type": "object"},
                },
                "required": ["note"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "VibeVoice license note: code MIT, weights MIT on "
                "the model-hub card, repository silent on weights; "
                "the three statements stay split and commercial use "
                "carries the research-only warning."
            ),
        )
    )
    return ["qa.vibevoice_license_note"]


__all__ = [
    "CODE_LICENSE",
    "CODE_LICENSE_HOLDER",
    "COMMERCIAL_USE",
    "REPO_WEIGHT_LICENSE",
    "WEIGHT_LICENSE",
    "WEIGHT_LICENSE_SOURCE",
    "check_vibevoice_license_note",
    "register_vibevoice_license_note_capabilities_once",
    "vibevoice_license_notes",
]
