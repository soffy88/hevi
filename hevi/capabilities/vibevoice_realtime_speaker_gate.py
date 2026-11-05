"""VibeVoice Realtime embedded-speaker gate (``qa.vibevoice_realtime_speaker_gate``).

Clean-room restatement of the VibeVoice review (see
``VIBEVOICE_ATTRIBUTION.md``): VibeVoice-Realtime-0.5B takes
voice prompts in embedded format only and accepts no
user-uploaded reference audio; a custom voice has to go
through the official team. English is the primary language
and the other embedded languages are experimental -- the
upstream documentation states they were not fully tested.
This gate judges a Realtime speaker plan only: the speaker
must be one of the 25 verified embedded names (or an
official-team custom voice with a contact record), the
language must match the speaker, and any non-English
language must be explicitly acknowledged as experimental.
No weight or audio file is referenced anywhere in hevi, and
this gate executes nothing: ``executed_here`` is always
false, and real inference is a separate GPU/real-machine case.
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
from hevi.capabilities.vibevoice_realtime_speaker_index import (
    EMBEDDED_SPEAKERS,
    PRIMARY_LANGUAGE,
    speaker_language,
)

_Registered = False

MODEL_ID = "vibevoice-realtime-0.5b"


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_vibevoice_realtime_speaker(plan: Any) -> dict[str, Any]:
    """Validate a VibeVoice-Realtime speaker plan.

    Verdicts are ``pass`` / ``fail`` only. Reference-audio
    and custom-upload speaker sources fail; only the embedded
    speaker list, or an official-team custom voice with a
    contact record, passes. A non-English language without an
    explicit experimental acknowledgement fails, as does a
    language that does not match the speaker.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "speaker_id": None,
            "language": None,
            "executed_here": False,
        }

    if not isinstance(plan, dict):
        return fail(
            "plan_not_object",
            "vibevoice realtime speaker plan must be a JSON object",
        )
    model = plan.get("model")
    if model is not None and model != MODEL_ID:
        return fail(
            "model_mismatch",
            "this gate judges vibevoice-realtime-0.5b plans only",
        )
    speaker_id = plan.get("speaker_id")
    if isinstance(speaker_id, str) and speaker_id.endswith(".pt"):
        return fail(
            "pt_file_not_in_hevi",
            "speaker ids are embedded names; weight files are never referenced in hevi",
        )
    if plan.get("speaker_pt_file") is not None:
        return fail(
            "pt_file_not_in_hevi",
            "speaker weight files are never referenced in hevi",
        )
    source = plan.get("speaker_source")
    if source == "official_team_custom":
        contact = plan.get("official_team_contact_ref")
        if not isinstance(contact, str) or not contact.strip():
            return fail(
                "official_team_contact_missing",
                "an official-team custom voice needs a contact record reference",
            )
        return {
            "verdict": "pass",
            "ok": True,
            "issues": [],
            "speaker_id": None,
            "language": plan.get("language"),
            "executed_here": False,
        }
    if source != "embedded":
        return fail(
            "reference_audio_refused",
            "Realtime takes embedded speaker prompts only; "
            "reference audio and custom uploads are refused, and "
            "a custom voice goes through the official team",
        )
    if not isinstance(speaker_id, str) or not speaker_id.strip():
        return fail(
            "speaker_id_missing",
            "an embedded speaker plan must name a speaker_id",
        )
    if speaker_id not in EMBEDDED_SPEAKERS:
        return fail(
            "unknown_embedded_speaker",
            "speaker_id must be one of the 25 verified upstream embedded names",
        )
    language = plan.get("language")
    if language != speaker_language(speaker_id):
        return fail(
            "language_speaker_mismatch",
            "language must match the embedded speaker's language "
            f"code ({speaker_language(speaker_id)!r})",
        )
    if language != PRIMARY_LANGUAGE and plan.get("experimental_language_acknowledged") is not True:
        return fail(
            "experimental_language_unacknowledged",
            "non-English embedded languages are experimental and "
            "must be explicitly acknowledged as such",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "speaker_id": speaker_id,
        "language": language,
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_vibevoice_realtime_speaker(params.get("plan"))
    report_path = out_dir / "vibevoice_realtime_speaker_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_vibevoice_realtime_speaker_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.vibevoice_realtime_speaker_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {"type": "object"},
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "VibeVoice Realtime embedded-speaker gate: only the "
                "25 verified embedded speaker names (or an "
                "official-team custom voice) pass; reference audio "
                "is refused and non-English languages must be "
                "acknowledged as experimental."
            ),
        )
    )
    return ["qa.vibevoice_realtime_speaker_gate"]


__all__ = [
    "MODEL_ID",
    "check_vibevoice_realtime_speaker",
    "register_vibevoice_realtime_speaker_gate_capabilities_once",
]
