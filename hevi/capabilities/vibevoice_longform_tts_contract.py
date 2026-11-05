"""VibeVoice long-form multi-speaker TTS contract (``video.vibevoice_longform_tts_contract``).

Fake-level contract for a VibeVoice-TTS-1.5B long-form
dialogue plan of the kind described in the VibeVoice review
(see ``VIBEVOICE_ATTRIBUTION.md``): up to 90 minutes in a
single pass, up to 4 speakers, English and Chinese, 24kHz
output, with optional word anchors. The contract certifies
the shape of the plan only. It runs no inference and
generates no audio: every compiled contract declares
``executed_here: false``, and any plan claiming inference
ran here fails outright. A reference-audio voice prompt
inside the dialogue is a clone equivalent and needs the
same authorization declaration the voice-prompt gate
requires. Whether a long dialogue sounds right is a
question for a real inference run, which is a separate
GPU/real-machine case.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

MODEL_ID = "vibevoice-tts-1.5b"
MAX_SINGLE_PASS_MINUTES = 90
MAX_SPEAKERS = 4
SAMPLE_RATE_HZ = 24000
LANGUAGES: frozenset[str] = frozenset({"en", "zh"})

_CLONE_MARKERS: frozenset[str] = frozenset(
    {"clone", "clone_voice", "voice_clone", "zero_shot_clone", "zero-shot-clone"}
)
_REFERENCE_AUDIO_SOURCES: frozenset[str] = frozenset(
    {"reference_audio", "voice_ref", "audio_file", "reference-clip"}
)


def _find_clone_markers(node: Any, path: str, found: list[str]) -> None:
    """Collect paths where a voice-clone request hides in a plan."""
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}" if path else str(key)
            if key in _CLONE_MARKERS:
                found.append(child)
            if key == "kind" and value in _CLONE_MARKERS:
                found.append(child)
            if key == "cloned" and value is True:
                found.append(child)
            _find_clone_markers(value, child, found)
    elif isinstance(node, list):
        for position, value in enumerate(node):
            _find_clone_markers(value, f"{path}[{position}]", found)


def _authorization_ok(auth: Any) -> bool:
    if not isinstance(auth, dict):
        return False
    voice_id = auth.get("voice_id")
    if not isinstance(voice_id, str) or not voice_id.strip():
        return False
    if auth.get("authorization_kind") not in ("own", "licensed"):
        return False
    evidence = auth.get("evidence_ref")
    return isinstance(evidence, str) and bool(evidence.strip())


def compile_vibevoice_longform_tts_contract(plan: Any) -> dict[str, Any]:
    """Compile one long-form multi-speaker TTS contract.

    ``plan`` carries ``model``, ``dialogue`` (a non-empty
    list of ``{speaker, text}`` lines), and optionally
    ``single_pass_minutes``, ``sample_rate_hz``,
    ``languages``, and ``word_anchor``. Raises
    :class:`CapabilityError` on any shape violation, on more
    than 4 speakers, on a single pass beyond 90 minutes, on
    a sample rate other than 24kHz, on languages outside
    English/Chinese, on a word-anchor claim without per-line
    anchors, on any clone request, on a reference-audio voice
    prompt without an authorization declaration, or on any
    claim that inference ran here. The returned contract
    records that nothing was executed here.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("long-form TTS plan must be an object")
    if plan.get("model") != MODEL_ID:
        raise CapabilityError("long-form TTS contract is for vibevoice-tts-1.5b only")
    if plan.get("executed_here") is True or plan.get("inference_ran") is True:
        raise CapabilityError("inference claims are refused here; this contract executes nothing")
    markers: list[str] = []
    _find_clone_markers(plan, "", markers)
    if markers:
        raise CapabilityError(
            f"voice cloning is never available; clone request intercepted at {markers[0]}"
        )
    dialogue = plan.get("dialogue")
    if not isinstance(dialogue, list) or not dialogue:
        raise CapabilityError("long-form TTS plan requires a non-empty dialogue list")
    speakers: list[str] = []
    needs_authorization = False
    word_anchor = plan.get("word_anchor") is True
    for position, line in enumerate(dialogue):
        if not isinstance(line, dict):
            raise CapabilityError(f"dialogue line {position} must be an object")
        speaker = line.get("speaker")
        if not isinstance(speaker, str) or not speaker.strip():
            raise CapabilityError(f"dialogue line {position} requires a speaker")
        if speaker not in speakers:
            speakers.append(speaker)
        text = line.get("text")
        if not isinstance(text, str) or not text.strip():
            raise CapabilityError(f"dialogue line {position} requires non-empty text")
        prompt = line.get("voice_prompt")
        if isinstance(prompt, dict) and prompt.get("source") in _REFERENCE_AUDIO_SOURCES:
            needs_authorization = True
        ref = line.get("voice_ref")
        if isinstance(ref, str) and ref.strip():
            needs_authorization = True
        if word_anchor and not isinstance(line.get("word_anchors"), list):
            raise CapabilityError(
                f"dialogue line {position} needs a word_anchors list when word_anchor is true"
            )
    if len(speakers) > MAX_SPEAKERS:
        raise CapabilityError("long-form TTS contract covers at most 4 speakers")
    if needs_authorization and not _authorization_ok(plan.get("voice_authorization")):
        raise CapabilityError(
            "a reference-audio voice prompt needs a voice "
            "authorization declaration (voice id, own or licensed "
            "kind, evidence reference)"
        )
    minutes = plan.get("single_pass_minutes")
    if isinstance(minutes, (int, float)) and minutes > MAX_SINGLE_PASS_MINUTES:
        raise CapabilityError("long-form TTS contract caps a single pass at 90 minutes")
    sample_rate = plan.get("sample_rate_hz")
    if sample_rate is not None and sample_rate != SAMPLE_RATE_HZ:
        raise CapabilityError("long-form TTS contract sample rate is 24000 Hz")
    languages = plan.get("languages")
    if isinstance(languages, list) and any(lang not in LANGUAGES for lang in languages):
        raise CapabilityError("long-form TTS contract covers English and Chinese only")
    return {
        "contract": "vibevoice-longform-tts",
        "model": MODEL_ID,
        "speakers": speakers,
        "speaker_count": len(speakers),
        "lines": len(dialogue),
        "single_pass_minutes": minutes,
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "languages": languages,
        "word_anchor": word_anchor,
        "executed_here": False,
        "inference_case": "separate_gpu_or_cloud_case",
        "gpu_required": True,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = compile_vibevoice_longform_tts_contract(params.get("plan"))
    report_path = out_dir / "vibevoice_longform_tts_contract.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "speaker_count": report["speaker_count"],
            "executed_here": False,
        },
    )


def register_vibevoice_longform_tts_contract_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.vibevoice_longform_tts_contract",
            kind="video",
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
            layer="obase",
            description=(
                "VibeVoice long-form multi-speaker TTS contract (fake): "
                "up to 90 minutes, 4 speakers, English/Chinese, "
                "24kHz, optional word anchors; no inference runs here."
            ),
        )
    )
    return ["video.vibevoice_longform_tts_contract"]


__all__ = [
    "LANGUAGES",
    "MAX_SINGLE_PASS_MINUTES",
    "MAX_SPEAKERS",
    "MODEL_ID",
    "SAMPLE_RATE_HZ",
    "compile_vibevoice_longform_tts_contract",
    "register_vibevoice_longform_tts_contract_capabilities_once",
]
