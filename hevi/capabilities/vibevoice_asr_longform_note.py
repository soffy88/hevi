"""VibeVoice ASR long-form method note (``qa.vibevoice_asr_longform_note``).

Clean-room restatement of the VibeVoice review (see
``VIBEVOICE_ATTRIBUTION.md``): VibeVoice-ASR-7B is specified
for a 60-minute single pass in 50+ languages with Who/When/
What structured output, custom hotwords, a streaming
variant, and a vLLM plugin; the BitNet variant runs on CPU
(about 1.58 GB, 3+ threads, real-time factor under 1). This
is a method note only: hevi has not implemented this ASR
shape, and the BitNet CPU engine is an ASR engine, never a
TTS solution. This module records the note only; it executes
nothing.
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

ASR_MODEL_ID = "vibevoice-asr-7b"
ASR_SINGLE_PASS_MINUTES = 60
ASR_LANGUAGES = "50+"
ASR_STRUCTURED_OUTPUT: tuple[str, ...] = ("who", "when", "what")
ASR_EXTRA_FIELDS: tuple[str, ...] = ("hotwords",)


def vibevoice_asr_notes() -> dict[str, Any]:
    """Return the recorded VibeVoice ASR long-form method note."""
    return {
        "model": ASR_MODEL_ID,
        "single_pass_minutes": ASR_SINGLE_PASS_MINUTES,
        "languages": ASR_LANGUAGES,
        "structured_output": list(ASR_STRUCTURED_OUTPUT),
        "hotwords": True,
        "streaming_variant": True,
        "vllm_plugin": True,
        "bitnet_cpu": {
            "size_gb": 1.58,
            "threads": "3+",
            "rtf": "<1",
            "is_tts": False,
        },
        "method_note_only": True,
        "executed_here": False,
    }


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_vibevoice_asr_note(note: Any) -> dict[str, Any]:
    """Validate a VibeVoice ASR long-form method note.

    Verdicts are ``pass`` / ``fail`` only. Claims that hevi
    already implements this ASR shape fail; claims that the
    BitNet CPU engine is a TTS solution fail; single-pass
    claims beyond 60 minutes fail; structured-output fields
    outside who/when/what (plus hotwords) fail.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "method_note_only": True,
            "executed_here": False,
        }

    if not isinstance(note, dict):
        return fail(
            "note_not_object",
            "vibevoice ASR note must be a JSON object",
        )
    if note.get("claims_hevi_implements") is True:
        return fail(
            "asr_not_implemented_here",
            "the VibeVoice ASR long-form shape is a method note only; hevi has not implemented it",
        )
    if note.get("claims_tts_solution") is True:
        return fail(
            "bitnet_not_tts",
            "the BitNet CPU engine is an ASR engine, never a TTS solution",
        )
    bitnet = note.get("bitnet_cpu")
    if isinstance(bitnet, dict) and bitnet.get("is_tts") is True:
        return fail(
            "bitnet_not_tts",
            "the BitNet CPU engine is an ASR engine, never a TTS solution",
        )
    minutes = note.get("single_pass_minutes")
    if isinstance(minutes, (int, float)) and minutes > ASR_SINGLE_PASS_MINUTES:
        return fail(
            "exceeds_asr_single_pass",
            "ASR single-pass claims are capped at 60 minutes",
        )
    fields = note.get("structured_output")
    if isinstance(fields, list) and any(
        field not in ASR_STRUCTURED_OUTPUT + ASR_EXTRA_FIELDS for field in fields
    ):
        return fail(
            "unknown_structured_field",
            "ASR structured output covers who/when/what (plus hotwords) only",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "method_note_only": True,
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_vibevoice_asr_note(params.get("note"))
    report_path = out_dir / "vibevoice_asr_longform_note_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_vibevoice_asr_longform_note_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.vibevoice_asr_longform_note",
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
                "VibeVoice ASR long-form method note: 60-minute "
                "single pass with who/when/what output, recorded "
                "as method only; BitNet CPU is ASR, never a TTS "
                "solution."
            ),
        )
    )
    return ["qa.vibevoice_asr_longform_note"]


__all__ = [
    "ASR_EXTRA_FIELDS",
    "ASR_LANGUAGES",
    "ASR_MODEL_ID",
    "ASR_SINGLE_PASS_MINUTES",
    "ASR_STRUCTURED_OUTPUT",
    "check_vibevoice_asr_note",
    "register_vibevoice_asr_longform_note_capabilities_once",
    "vibevoice_asr_notes",
]
