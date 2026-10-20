"""Multi-model pipeline capabilities (cloud providers via Monid).

Registers three ``hevi.capabilities`` entries so every product line can invoke
the cloud-backed pieces of the multi-model pipeline by dotted name
(CAPABILITY_CONTRACT.md, user addendum 2026-10-14; precedent:
``motion.review`` and ``agent.ops_bridge``):

* ``audio.forced_align`` — measured word-level timestamps (ElevenLabs forced
  alignment via Monid, $0.22/audio-hour). Use when real millisecond word
  boundaries are needed (subtitle burn-in, word-level cuts, snap_to_word).
  Unlike the LuxTTS duration-weighted estimates, the result is
  ``is_estimated=False``.
* ``image.gpt_generate`` — GPT-Image 2.5 text-to-image (Monid). High-aesthetic
  scene/character stills when the local GPU route is unavailable.
* ``image.gpt_edit`` — GPT-Image 2.5 reference-based edit (up to 16 refs).
  The character-consistency workflow: lock a character sheet once, then
  re-pose / re-scene from the same references.

Provider keys: ``MONID_API_KEY`` in the environment (Monid REST, X-Monid-Client
hevi). The modules raise ``monid_client.MonidError`` when it is missing, and
``render`` surfaces that as ``CapabilityError`` — never a fake success.
"""

from __future__ import annotations

import asyncio
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

_MULTIMODEL_COST_NOTE = (
    "Billed per Monid endpoint rate against the workspace balance; "
    "see run output 'cost' in the qa report."
)


def _run_coro(coro):
    """Run an async service call from the synchronous capability render."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        # render() is sync per contract; offload to a fresh thread + loop.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


def _render_forced_align(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.audio.forced_alignment import forced_align_words
    from hevi.audio.monid_client import MonidError

    audio_path = Path(params["audio_path"])
    text = str(params["text"])
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        words, cost = _run_coro(
            forced_align_words(audio_path=audio_path, text=text)
        )
    except MonidError as exc:
        raise CapabilityError(f"audio.forced_align: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - contract wants CapabilityError
        raise CapabilityError(f"audio.forced_align failed: {exc}") from exc

    sidecar = out_dir / "alignment.json"
    sidecar.write_text(
        json.dumps(
            {
                "audio_path": str(audio_path),
                "alignment_source": "elevenlabs_forced_alignment",
                "is_estimated": False,
                "cost": cost,
                "words": [
                    {"text": w.text, "start_ms": w.start_ms, "end_ms": w.end_ms}
                    for w in words
                ],
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    duration_s = max((w.end_ms for w in words), default=0) / 1000.0
    return CapabilityResult(
        wav=str(audio_path),
        duration_s=duration_s,
        sha256=compute_sha256(audio_path),
        qa={
            "alignment_json": str(sidecar),
            "word_count": len(words),
            "is_estimated": False,
            "cost": cost,
            "note": _MULTIMODEL_COST_NOTE,
        },
    )


def _render_image(
    generate: bool,
    params: dict[str, Any],
    out_dir: Path,
    *,
    duration: float,
    aspect: str,
    seed: int,
) -> CapabilityResult:
    from hevi.audio.monid_client import MonidError
    from hevi.image import gpt_image_service

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    png_path = out_dir / "image.png"
    call_kwargs: dict[str, Any] = {
        "prompt": str(params["prompt"]),
        "output_path": png_path,
        "size": str(params.get("size", "1024x1536")),
        "quality": str(params.get("quality", "medium")),
    }
    name = "image.gpt_generate" if generate else "image.gpt_edit"
    try:
        if generate:
            result = _run_coro(gpt_image_service.gpt_image_generate(**call_kwargs))
        else:
            result = _run_coro(
                gpt_image_service.gpt_image_edit(
                    image_paths=[Path(p) for p in params["image_paths"]],
                    **call_kwargs,
                )
            )
    except MonidError as exc:
        raise CapabilityError(f"{name}: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - contract wants CapabilityError
        raise CapabilityError(f"{name} failed: {exc}") from exc

    return CapabilityResult(
        png=str(png_path),
        duration_s=0.0,
        sha256=compute_sha256(png_path),
        qa={
            "cost": result.get("cost"),
            "size": call_kwargs["size"],
            "quality": call_kwargs["quality"],
            "note": _MULTIMODEL_COST_NOTE,
        },
    )


def _render_gpt_generate(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    return _render_image(True, params, out_dir, duration=duration, aspect=aspect, seed=seed)


def _render_gpt_edit(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    return _render_image(False, params, out_dir, duration=duration, aspect=aspect, seed=seed)


def register_multimodel_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    registered: list[str] = []

    register(
        Capability(
            name="audio.forced_align",
            kind="audio",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "audio_path": {
                        "type": "string",
                        "description": "Local audio file (wav/mp3, <=20MB)",
                    },
                    "text": {
                        "type": "string",
                        "minLength": 1,
                        "description": "The exact transcript spoken in the audio",
                    },
                },
                "required": ["audio_path", "text"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,  # cloud endpoint; local cost is upload + poll only
            render=_render_forced_align,
            description=(
                "Measured word-level {text, start_ms, end_ms} timestamps from real "
                "audio via ElevenLabs forced alignment (Monid). Use instead of "
                "LuxTTS estimated timings when millisecond accuracy matters "
                "(subtitle burn, word-level cuts). Result marks is_estimated=False."
            ),
            line="multimodel",
        )
    )
    registered.append("audio.forced_align")

    image_schema_base = {
        "prompt": {"type": "string", "minLength": 1},
        "size": {
            "type": "string",
            "default": "1024x1536",
            "description": "WIDTHxHEIGHT, multiples of 16, aspect 1:3..3:1",
        },
        "quality": {
            "type": "string",
            "enum": ["low", "medium", "high", "max"],
            "default": "medium",
        },
    }
    register(
        Capability(
            name="image.gpt_generate",
            kind="shot",
            aspects=["9:16", "16:9", "1:1"],
            params_schema={
                "type": "object",
                "properties": image_schema_base,
                "required": ["prompt"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render_gpt_generate,
            description=(
                "GPT-Image 2.5 text-to-image stills (Monid). Use for high-aesthetic "
                "studio scenes and character sheets when the local GPU route is "
                "unavailable."
            ),
            line="multimodel",
        )
    )
    registered.append("image.gpt_generate")

    edit_schema = dict(image_schema_base)
    edit_schema["image_paths"] = {
        "type": "array",
        "items": {"type": "string"},
        "minItems": 1,
        "maxItems": 16,
        "description": "Reference images for character-consistent editing",
    }
    register(
        Capability(
            name="image.gpt_edit",
            kind="shot",
            aspects=["9:16", "16:9", "1:1"],
            params_schema={
                "type": "object",
                "properties": edit_schema,
                "required": ["image_paths", "prompt"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render_gpt_edit,
            description=(
                "GPT-Image 2.5 reference-based edit from up to 16 images (Monid). "
                "The character-consistency workflow: same face/clothing/scene "
                "across poses and angles."
            ),
            line="multimodel",
        )
    )
    registered.append("image.gpt_edit")

    return registered
