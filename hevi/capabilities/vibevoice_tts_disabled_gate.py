"""VibeVoice TTS-1.5B disabled-path gate (``qa.vibevoice_tts_disabled_gate``).

Clean-room restatement of the VibeVoice review (see
``VIBEVOICE_ATTRIBUTION.md``): Microsoft removed the official
VibeVoice-TTS-1.5B code path on 2025-09-05 after widespread
misuse, and the TTS usage documentation states installation
and usage are disabled. The weights remain on the model hub,
but running them is a third-party reproduction, not an
official path. This gate judges claims about the 1.5B path
only: any claim that official code runs, or that the official
path is available, fails. A third-party or hevi-worker
implementation passes only when it declares itself
non-official and unverified, and declares the official path
disabled. This gate executes nothing: ``executed_here`` is
always false, and real inference is a separate GPU/real-machine
case.
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

MODEL_ID = "vibevoice-tts-1.5b"

_NON_OFFICIAL_IMPLEMENTATIONS: tuple[str, str] = (
    "third_party_reproduction",
    "hevi_oprim_worker",
)


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_vibevoice_tts_disabled(claim: Any) -> dict[str, Any]:
    """Validate a claim about the VibeVoice-TTS-1.5B path.

    Verdicts are ``pass`` / ``fail`` only. Claims that the
    official code runs or the official path is available fail;
    an implementation other than the official one must declare
    itself non-official and unverified, and the claim must
    declare the official path disabled.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "model": MODEL_ID,
            "implementation": None,
            "executed_here": False,
        }

    if not isinstance(claim, dict):
        return fail(
            "claim_not_object",
            "vibevoice TTS-1.5B claim must be a JSON object",
        )
    model = claim.get("model")
    if not isinstance(model, str) or not model.strip():
        return fail(
            "model_missing",
            "claim must name the model (vibevoice-tts-1.5b)",
        )
    if model != MODEL_ID:
        return fail(
            "model_mismatch",
            "this gate judges vibevoice-tts-1.5b claims only",
        )
    if claim.get("official_path_available") is True:
        return fail(
            "official_path_claimed",
            "the official VibeVoice-TTS-1.5B path is disabled; it cannot be claimed available",
        )
    if claim.get("official_code_runs") is True:
        return fail(
            "official_code_claimed",
            "official VibeVoice-TTS-1.5B code was removed; it cannot be claimed to run",
        )
    implementation = claim.get("implementation")
    if implementation == "official":
        return fail(
            "official_path_claimed",
            "implementation 'official' is unavailable: the official code path was removed",
        )
    if claim.get("declares_disabled") is not True:
        return fail(
            "disabled_not_declared",
            "claim must declare the official TTS-1.5B path disabled",
        )
    if implementation in _NON_OFFICIAL_IMPLEMENTATIONS:
        if claim.get("declares_non_official") is not True:
            return fail(
                "reproduction_not_declared_non_official",
                "a third-party or hevi-worker implementation must declare itself non-official",
            )
        if claim.get("declares_unverified") is not True:
            return fail(
                "reproduction_not_declared_unverified",
                "a third-party or hevi-worker implementation must declare itself unverified here",
            )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "model": MODEL_ID,
        "implementation": implementation,
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_vibevoice_tts_disabled(params.get("claim"))
    report_path = out_dir / "vibevoice_tts_disabled_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_vibevoice_tts_disabled_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.vibevoice_tts_disabled_gate",
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
                "VibeVoice TTS-1.5B disabled-path gate: the official "
                "code path was removed, so any claim it runs fails; "
                "third-party or hevi-worker implementations must "
                "declare themselves non-official and unverified."
            ),
        )
    )
    return ["qa.vibevoice_tts_disabled_gate"]


__all__ = [
    "MODEL_ID",
    "check_vibevoice_tts_disabled",
    "register_vibevoice_tts_disabled_gate_capabilities_once",
]
