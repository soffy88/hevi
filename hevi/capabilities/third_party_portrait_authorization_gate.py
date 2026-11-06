"""Third-party portrait authorization gate (``qa.third_party_portrait_authorization_gate``).

Clean-room addition to the ChrisHKAI-Video creator-intro
method (see ``CHRISHKAI_VIDEO_ATTRIBUTION.md``): the
reviewed method assumes the maker is the creator and carries
no identity check of its own — anyone could paste someone
else's page and start a film. That gap must not be copied.
This gate fills that gap: when the requester is not the creator
themselves, a portrait may only be used with authorization
evidence, and a minor creator's portrait is hard-blocked
under hevi's minor hard-intercept rule, evidence or not.
It connects to ``qa.portrait_consent_gate``, which governs
authorised portraits. This gate judges the authorization
record only. It generates nothing: ``executed_here`` is
always false.
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


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_third_party_portrait_authorization(request: Any) -> dict[str, Any]:
    """Validate a third-party portrait authorization request.

    Pass requires either that the requester is the creator
    themselves, or authorization evidence for a third-party
    creator. A minor creator's portrait is hard-blocked
    under the minor hard-intercept rule, with or without
    evidence.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(request, dict):
        return fail("request_not_object", "request must be a JSON object")
    if request.get("creator_is_minor") is True:
        return fail(
            "minor_blocked",
            "a minor creator's portrait is hard-blocked under the minor hard-intercept rule",
        )
    if request.get("creator_is_requester") is True:
        return {
            "verdict": "pass",
            "ok": True,
            "issues": [],
            "executed_here": False,
        }
    if not request.get("authorization_evidence"):
        return fail(
            "missing_authorization",
            "a third-party creator's portrait requires authorization evidence; none was given",
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
    report = check_third_party_portrait_authorization(params.get("request"))
    report_path = out_dir / "third_party_portrait_authorization_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_third_party_portrait_authorization_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.third_party_portrait_authorization_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "request": {"type": "object"},
                },
                "required": ["request"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Third-party portrait authorization gate: the "
                "requester is the creator, or authorization evidence "
                "is required; a minor creator's portrait is "
                "hard-blocked. Complements qa.portrait_consent_gate."
            ),
        )
    )
    return ["qa.third_party_portrait_authorization_gate"]


__all__ = [
    "check_third_party_portrait_authorization",
    "register_third_party_portrait_authorization_gate_capabilities_once",
]
