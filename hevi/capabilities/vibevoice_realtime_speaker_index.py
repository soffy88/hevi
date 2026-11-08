"""VibeVoice Realtime embedded-speaker index (``video.vibevoice_realtime_speaker_index``).

Fake-level contract for the embedded-speaker index of
VibeVoice-Realtime-0.5B, restated from the VibeVoice review
(see ``VIBEVOICE_ATTRIBUTION.md``). The upstream model takes
voice prompts in embedded format only and accepts no
user-uploaded reference audio; the 25 embedded speaker names
below were verified against the upstream
``demo/voices/streaming_model/`` file listing (names only --
no audio, no weight files, nothing downloaded). The contract
certifies the shape of an index only: it holds names,
languages, and styles, and records that nothing was executed
here. Whether a speaker sounds right is a question for a
real inference run, which is a separate GPU/real-machine case.
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

# Embedded speaker names verified against the upstream
# demo/voices/streaming_model/ listing (25 files, names only).
# Language code is the prefix before "-"; style is the suffix
# ("man" / "woman"). English is the model's primary language;
# every other language code is treated as experimental.
EMBEDDED_SPEAKERS: tuple[str, ...] = (
    "de-Spk0_man",
    "de-Spk1_woman",
    "en-Carter_man",
    "en-Davis_man",
    "en-Emma_woman",
    "en-Frank_man",
    "en-Grace_woman",
    "en-Mike_man",
    "fr-Spk0_man",
    "fr-Spk1_woman",
    "in-Samuel_man",
    "it-Spk0_woman",
    "it-Spk1_man",
    "jp-Spk0_man",
    "jp-Spk1_woman",
    "kr-Spk0_man",
    "kr-Spk1_man",
    "nl-Spk0_man",
    "nl-Spk1_woman",
    "pl-Spk0_man",
    "pl-Spk1_woman",
    "pt-Spk0_woman",
    "pt-Spk1_man",
    "sp-Spk0_woman",
    "sp-Spk1_man",
)

PRIMARY_LANGUAGE = "en"


def speaker_language(speaker_id: str) -> str:
    """Return the language code carried by an embedded speaker id."""
    return speaker_id.split("-", 1)[0]


def speaker_style(speaker_id: str) -> str:
    """Return the style suffix carried by an embedded speaker id."""
    return speaker_id.rsplit("_", 1)[-1]


def compile_vibevoice_realtime_speaker_index(index: Any) -> dict[str, Any]:
    """Compile one Realtime embedded-speaker index contract.

    ``index`` carries ``speakers``, a non-empty list of
    ``{speaker_id, language, style, format}`` entries. Raises
    :class:`CapabilityError` on any shape violation, on an
    unknown speaker id, on a language or style that does not
    match the id, on any non-embedded format, on duplicate
    ids, or on any reference to a weight or audio file. The
    returned contract records that nothing was executed here
    and no audio is included.
    """
    if not isinstance(index, dict):
        raise CapabilityError("speaker index must be an object")
    speakers = index.get("speakers")
    if not isinstance(speakers, list) or not speakers:
        raise CapabilityError("speaker index requires a non-empty speakers list")
    seen: set[str] = set()
    compiled: list[dict[str, str]] = []
    for position, speaker in enumerate(speakers):
        if not isinstance(speaker, dict):
            raise CapabilityError(f"speaker {position} must be an object")
        speaker_id = speaker.get("speaker_id")
        if not isinstance(speaker_id, str) or not speaker_id.strip():
            raise CapabilityError(f"speaker {position} requires a speaker_id")
        if speaker_id in seen:
            raise CapabilityError(f"duplicate speaker_id {speaker_id!r}")
        seen.add(speaker_id)
        if speaker_id not in EMBEDDED_SPEAKERS:
            raise CapabilityError(
                f"unknown embedded speaker {speaker_id!r}; only the "
                "25 verified upstream embedded names are allowed"
            )
        language = speaker.get("language")
        if language != speaker_language(speaker_id):
            raise CapabilityError(
                f"speaker {speaker_id!r} language must be {speaker_language(speaker_id)!r}"
            )
        style = speaker.get("style")
        if style != speaker_style(speaker_id):
            raise CapabilityError(
                f"speaker {speaker_id!r} style must be {speaker_style(speaker_id)!r}"
            )
        if speaker.get("format") != "embedded":
            raise CapabilityError(f"speaker {speaker_id!r} format must be 'embedded'")
        for key, value in speaker.items():
            if isinstance(value, str) and (value.endswith(".pt") or "voices/" in value):
                raise CapabilityError(
                    f"speaker entries must not reference weight or audio files ({key})"
                )
        if "reference_audio" in speaker:
            raise CapabilityError("speaker entries must not carry reference audio")
        compiled.append(
            {
                "speaker_id": speaker_id,
                "language": language,
                "style": style,
                "format": "embedded",
            }
        )
    return {
        "index": "vibevoice-realtime-embedded-speakers",
        "speaker_count": len(compiled),
        "speakers": compiled,
        "audio_included": False,
        "weights_downloaded": False,
        "executed_here": False,
        "rendered_here": False,
        "output_file": None,
        "experimental_languages_require_acknowledgement": True,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = compile_vibevoice_realtime_speaker_index(params.get("index"))
    report_path = out_dir / "vibevoice_realtime_speaker_index_contract.json"
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


def register_vibevoice_realtime_speaker_index_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.vibevoice_realtime_speaker_index",
            kind="video",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "index": {"type": "object"},
                },
                "required": ["index"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="obase",
            description=(
                "VibeVoice Realtime embedded-speaker index (fake "
                "contract): the 25 verified upstream embedded speaker "
                "names with language and style; no audio, no weights, "
                "nothing executed here."
            ),
        )
    )
    return ["video.vibevoice_realtime_speaker_index"]


__all__ = [
    "EMBEDDED_SPEAKERS",
    "PRIMARY_LANGUAGE",
    "compile_vibevoice_realtime_speaker_index",
    "register_vibevoice_realtime_speaker_index_capabilities_once",
    "speaker_language",
    "speaker_style",
]
