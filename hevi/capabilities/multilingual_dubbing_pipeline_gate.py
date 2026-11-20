"""Multilingual dubbing pipeline gate (``qa.multilingual_dubbing_pipeline_gate``).

hevi's own method increment for the multilingual dubbing
pipeline: recognize, translate, synthesize, align, mix. The
post linked ``alwaysmavs/video-dubbing`` for this function, but
that repository does not exist (checked 2026-11-20, see
``VIDEO_SKILLS_10_ATTRIBUTION.md``), so this gate is written
from hevi's own pipeline, not from any upstream file; no
upstream code appears in it.

hevi already owns the voice-authorization gates
(``qa.cosyvoice_authorization_gate``,
``video.freevideo_dubbing_task_schema``, the VibeVoice speaker
gate). This gate owns only the pipeline that strings them
together: the five stages in order, a declared source and
target language, forced alignment declared, and a voice that
carries an authorization proof. Only authorized voices run
(LuxTTS ``soffy``, CosyVoice authorized voices); zero-shot
cloning and any clone mode always fail, and ElevenLabs is
never accepted.
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

STAGES = ("transcribe", "translate", "tts", "align", "mix")
AUTHORIZED_PROVIDERS = ("luxtts", "cosyvoice")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _subsequence(stages: list[str]) -> bool:
    cursor = 0
    for wanted in STAGES:
        while cursor < len(stages) and stages[cursor] != wanted:
            cursor += 1
        if cursor >= len(stages):
            return False
        cursor += 1
    return True


def check_multilingual_dubbing_pipeline(plan: Any) -> dict[str, Any]:
    """Validate a multilingual dubbing pipeline plan.

    Verdicts are ``pass`` / ``fail`` only. A plan fails when
    it is not an object, when source or target language is
    missing or the two are equal, when the stages do not run
    transcribe, translate, tts, align, mix in that order, when
    alignment is not declared, when the voice lacks an
    authorization proof, when the voice provider is outside
    the authorized set, when any clone or zero-shot mode is
    requested, or when the plan names ElevenLabs.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(plan, dict):
        return fail("plan_not_object", "dubbing pipeline plan must be a JSON object")
    if "elevenlabs" in json.dumps(plan, ensure_ascii=False).lower():
        return fail(
            "elevenlabs_not_accepted",
            "ElevenLabs is never accepted in a dubbing pipeline; "
            "dubbing uses authorized voices only",
        )
    for field in (
        "source_language",
        "target_language",
        "stages",
        "voice",
        "alignment",
    ):
        if field not in plan:
            return fail("plan_field_missing", f"dubbing pipeline plan must carry {field!r}")
    source = plan["source_language"]
    target = plan["target_language"]
    if not isinstance(source, str) or not source:
        return fail("source_language_missing", "source_language must be a non-empty string")
    if not isinstance(target, str) or not target:
        return fail("target_language_missing", "target_language must be a non-empty string")
    if source == target:
        return fail(
            "languages_equal",
            "source_language and target_language must differ",
        )
    stages = plan["stages"]
    if not isinstance(stages, list) or not all(isinstance(s, str) for s in stages):
        return fail("stages_not_list", "stages must be a list of stage names")
    if not _subsequence(stages):
        return fail(
            "stages_out_of_order",
            "stages must run transcribe, translate, tts, align, mix in that order",
        )
    if plan["alignment"] is not True:
        return fail(
            "alignment_missing",
            "alignment must be declared true; dubbing is aligned, never drifted",
        )
    voice = plan["voice"]
    if not isinstance(voice, dict):
        return fail("voice_not_object", "voice must be an object")
    if not isinstance(voice.get("voice_id"), str) or not voice["voice_id"]:
        return fail("voice_id_missing", "voice must name a voice_id")
    if not isinstance(voice.get("authorization_proof"), str) or not voice["authorization_proof"]:
        return fail(
            "voice_authorization_missing",
            "voice must carry an authorization proof; unproven voices fail",
        )
    provider = voice.get("provider")
    if not isinstance(provider, str) or provider.lower() not in AUTHORIZED_PROVIDERS:
        return fail(
            "voice_provider_not_authorized",
            "voice provider must be one of: " + ", ".join(AUTHORIZED_PROVIDERS),
        )
    if voice.get("clone") is True or voice.get("mode") == "clone":
        return fail(
            "clone_not_accepted",
            "clone mode is never accepted in a dubbing pipeline",
        )
    if voice.get("zero_shot") is True:
        return fail(
            "zero_shot_not_accepted",
            "zero-shot voice reference is a clone equivalent and is never accepted",
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
    report = check_multilingual_dubbing_pipeline(params.get("plan"))
    report_path = out_dir / "multilingual_dubbing_pipeline_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_multilingual_dubbing_pipeline_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.multilingual_dubbing_pipeline_gate",
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
                "Multilingual dubbing pipeline gate: transcribe, translate, "
                "tts, align, mix in order, forced alignment declared, voice "
                "with an authorization proof; authorized voices only, clone "
                "and zero-shot modes always fail, ElevenLabs never accepted."
            ),
        )
    )
    return ["qa.multilingual_dubbing_pipeline_gate"]


__all__ = [
    "STAGES",
    "check_multilingual_dubbing_pipeline",
    "register_multilingual_dubbing_pipeline_gate_capabilities_once",
]
