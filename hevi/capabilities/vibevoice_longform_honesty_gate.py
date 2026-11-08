"""VibeVoice long-form / multi-speaker honesty gate (``qa.vibevoice_longform_honesty_gate``).

Clean-room restatement of the VibeVoice review (see
``VIBEVOICE_ATTRIBUTION.md``): VibeVoice-TTS-1.5B is
specified for about 90 minutes in a single pass with up to
4 speakers in English and Chinese, but that is a research
specification for a model whose official code path was
removed -- it is not a production capability here, and no
such run has been verified in hevi. VibeVoice-Realtime-0.5B
is a single-speaker model with an 8K context of about
10 minutes. This gate judges long-form claims only: a 1.5B
claim must declare the official path disabled and its
research status, and must never claim production or verified
status; a Realtime claim must stay inside its 10-minute,
single-speaker envelope. This gate executes nothing:
``executed_here`` is always false, and real inference is a
separate GPU/real-machine case.
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

TTS_MODEL_ID = "vibevoice-tts-1.5b"
REALTIME_MODEL_ID = "vibevoice-realtime-0.5b"

TTS_SINGLE_PASS_MINUTES = 90
TTS_MAX_SPEAKERS = 4
TTS_LANGUAGES: frozenset[str] = frozenset({"en", "zh"})
REALTIME_SINGLE_PASS_MINUTES = 10
REALTIME_MAX_SPEAKERS = 1


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_vibevoice_longform_honesty(claim: Any) -> dict[str, Any]:
    """Validate a VibeVoice long-form / multi-speaker claim.

    Verdicts are ``pass`` / ``fail`` only. A 1.5B claim must
    declare the official path disabled and its research
    status, and must never claim production or verified
    status. A Realtime claim must stay inside 10 minutes and
    a single speaker. Any claim beyond the recorded envelope
    fails.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "model": None,
            "executed_here": False,
        }

    if not isinstance(claim, dict):
        return fail(
            "claim_not_object",
            "vibevoice long-form claim must be a JSON object",
        )
    model = claim.get("model")
    if not isinstance(model, str) or not model.strip():
        return fail(
            "model_missing",
            "claim must name the model (vibevoice-tts-1.5b or vibevoice-realtime-0.5b)",
        )
    if model not in (TTS_MODEL_ID, REALTIME_MODEL_ID):
        return fail(
            "model_unknown",
            "this gate judges vibevoice-tts-1.5b and vibevoice-realtime-0.5b claims only",
        )
    kind = claim.get("claim_kind")
    if kind is None:
        return fail(
            "claim_kind_missing",
            "claim must declare a kind (research, production, or verified)",
        )
    if model == TTS_MODEL_ID:
        if kind in ("production", "verified"):
            return fail(
                "production_claim_refused",
                "the 1.5B long-form path is research status with "
                "its official code removed; production or verified "
                "claims are refused",
            )
        if claim.get("declares_official_disabled") is not True:
            return fail(
                "disabled_not_declared",
                "a 1.5B long-form claim must declare the official path disabled",
            )
        if claim.get("declares_research_status") is not True:
            return fail(
                "research_status_not_declared",
                "a 1.5B long-form claim must declare its research status",
            )
        minutes = claim.get("single_pass_minutes")
        if isinstance(minutes, (int, float)) and minutes > TTS_SINGLE_PASS_MINUTES:
            return fail(
                "exceeds_single_pass_limit",
                "1.5B single-pass claims are capped at 90 minutes",
            )
        speakers = claim.get("speakers")
        if isinstance(speakers, int) and speakers > TTS_MAX_SPEAKERS:
            return fail(
                "exceeds_speaker_limit",
                "1.5B multi-speaker claims are capped at 4 speakers",
            )
        languages = claim.get("languages")
        if isinstance(languages, list) and any(lang not in TTS_LANGUAGES for lang in languages):
            return fail(
                "language_unsupported",
                "1.5B long-form claims cover English and Chinese only",
            )
        return {
            "verdict": "pass",
            "ok": True,
            "issues": [],
            "model": model,
            "executed_here": False,
        }
    minutes = claim.get("single_pass_minutes")
    if isinstance(minutes, (int, float)) and minutes > REALTIME_SINGLE_PASS_MINUTES:
        return fail(
            "exceeds_realtime_context",
            "Realtime single-pass claims are capped at about 10 minutes (8K context)",
        )
    speakers = claim.get("speakers")
    if isinstance(speakers, int) and speakers > REALTIME_MAX_SPEAKERS:
        return fail(
            "realtime_single_speaker",
            "Realtime is a single-speaker model",
        )
    if kind == "verified" and not claim.get("measured_evidence"):
        return fail(
            "verified_claim_unsubstantiated",
            "a verified Realtime claim needs measured evidence",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "model": model,
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_vibevoice_longform_honesty(params.get("claim"))
    report_path = out_dir / "vibevoice_longform_honesty_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_vibevoice_longform_honesty_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.vibevoice_longform_honesty_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "claim": {"type": "object"},
                },
                "required": ["claim"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "VibeVoice long-form honesty gate: 1.5B 90-minute / "
                "4-speaker claims must declare the official path "
                "disabled and research status, never production; "
                "Realtime claims stay inside 10 minutes, one speaker."
            ),
        )
    )
    return ["qa.vibevoice_longform_honesty_gate"]


__all__ = [
    "REALTIME_MAX_SPEAKERS",
    "REALTIME_MODEL_ID",
    "REALTIME_SINGLE_PASS_MINUTES",
    "TTS_LANGUAGES",
    "TTS_MAX_SPEAKERS",
    "TTS_MODEL_ID",
    "TTS_SINGLE_PASS_MINUTES",
    "check_vibevoice_longform_honesty",
    "register_vibevoice_longform_honesty_gate_capabilities_once",
]
