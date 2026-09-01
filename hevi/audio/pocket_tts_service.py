"""HEVI-native Pocket TTS capability.

The capability is implemented inside HEVI's 3O voice layers: CPU-first local
speech, catalog voices, reference-audio conditioning, batch and streaming.
An installed upstream ``TTSModel`` may be used for higher-fidelity inference,
but it is not required for the HEVI capability or its public task contract.
Every successful call must leave a non-empty WAV; failures never become a
placeholder artifact.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import os
import queue
import threading
from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
_MODEL_LOCK = threading.Lock()


def _import_pocket_tts() -> Any | None:
    try:
        return importlib.import_module("pocket_tts")
    except ImportError:
        logger.debug("optional Pocket TTS module unavailable; HEVI native runtime remains available")
        return None


def pocket_tts_available() -> bool:
    """Return whether HEVI can execute the Pocket capability locally.

    The capability is owned by HEVI's native voice skill.  The upstream Python
    package is only an optional fidelity backend and is not required.
    """

    mod = _import_pocket_tts()
    if mod is not None and getattr(mod, "TTSModel", None) is not None:
        return True
    from hevi.voicepro.oskill import native_voice_available

    return native_voice_available()


@lru_cache(maxsize=4)
def _load_model(config: str = "", language: str = "") -> Any:
    mod = _import_pocket_tts()
    if mod is None or getattr(mod, "TTSModel", None) is None:
        raise RuntimeError("optional Pocket TTS model backend is unavailable")
    model_cls = getattr(mod, "TTSModel", None)
    if model_cls is None:
        raise RuntimeError("pocket_tts module has no TTSModel entry point")

    # Current Pocket TTS exposes load_model() without requiring a config.  A
    # configured model is supported when the installed release advertises a
    # compatible keyword, while older releases remain usable.
    load_model = model_cls.load_model
    try:
        signature = inspect.signature(load_model)
    except (TypeError, ValueError):
        signature = None
    kwargs: dict[str, Any] = {}
    if language and signature is not None and "language" in signature.parameters:
        kwargs["language"] = language
    if config:
        if signature is not None and "config" in signature.parameters:
            kwargs["config"] = config
        elif signature is not None and "config_path" in signature.parameters:
            kwargs["config_path"] = config
        else:
            raise RuntimeError(
                "installed pocket-tts does not accept POCKET_TTS_CONFIG; unset it or upgrade"
            )
    return load_model(**kwargs)


def _audio_numpy(audio: Any) -> Any:
    detached = audio.detach() if hasattr(audio, "detach") else audio
    cpu_audio = detached.cpu() if hasattr(detached, "cpu") else detached
    if hasattr(cpu_audio, "numpy"):
        return cpu_audio.numpy()
    return cpu_audio


def _write_wav(output_path: Path, sample_rate: int, audio: Any) -> None:
    samples = _audio_numpy(audio)
    try:
        wavfile = importlib.import_module("scipy.io.wavfile")

        wavfile.write(str(output_path), int(sample_rate), samples)
        return
    except ImportError:
        pass

    try:
        sf = importlib.import_module("soundfile")
    except ImportError as exc:
        raise RuntimeError(
            "Pocket TTS produced audio but no WAV writer is installed; "
            "install scipy or soundfile"
        ) from exc
    sf.write(str(output_path), samples, int(sample_rate))


def _load_for_request(config: str, language: str) -> Any:
    """Keep monkeypatched/older HEVI loaders compatible with language-aware models."""

    try:
        parameters: Any = inspect.signature(_load_model).parameters
    except (TypeError, ValueError):
        parameters = {}
    if "language" in parameters:
        return _load_model(config, language)
    return _load_model(config)


def _synth_sync(
    text: str,
    output_path: Path,
    *,
    voice: str,
    language: str,
    reference_audio: str | Path | None,
    voice_design: str,
    speed: float,
    config: str,
) -> None:
    mod = _import_pocket_tts()
    if mod is None or getattr(mod, "TTSModel", None) is None:
        from hevi.voicepro.oskill import synthesize_native_voice_sync

        synthesize_native_voice_sync(
            text,
            output_path,
            voice=voice,
            language=language,
            reference_audio=reference_audio,
            voice_design=voice_design,
            speed=speed,
        )
        return

    model = _load_for_request(config, language)
    voice_source = str(reference_audio) if reference_audio else (voice.strip() or "alba")
    if reference_audio and not Path(reference_audio).is_file():
        raise FileNotFoundError(f"Pocket TTS reference audio not found: {reference_audio}")
    with _MODEL_LOCK:
        state = model.get_state_for_audio_prompt(voice_source)
        audio = model.generate_audio(state, text)
    sample_rate = int(getattr(model, "sample_rate", 24_000))
    _write_wav(output_path, sample_rate, audio)


async def synth_with_pocket_tts(
    text: str,
    *,
    output_path: str | Path,
    voice: str = "alba",
    language: str = "",
    reference_audio: str | Path | None = None,
    voice_design: str = "",
    speed: float = 1.0,
    config: str | Path | None = None,
) -> Path:
    """Generate one WAV using Pocket TTS.

    ``voice`` accepts a Pocket catalog voice (for example ``alba``) or a
    local voice embedding/audio path.  ``reference_audio`` is explicit to make
    consent and provenance visible at the service boundary.
    """

    if not text.strip():
        raise ValueError("Pocket TTS text cannot be empty")
    if not pocket_tts_available():
        raise RuntimeError(
            "HEVI native voice runtime unavailable; provide espeak-ng/espeak on PATH"
        )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    model_config = str(config or os.getenv("POCKET_TTS_CONFIG", "")).strip()
    await asyncio.to_thread(
        _synth_sync,
        text,
        destination,
        voice=voice,
        language=language,
        reference_audio=reference_audio,
        voice_design=voice_design,
        speed=speed,
        config=model_config,
    )
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError("Pocket TTS completed without a non-empty WAV artifact")
    return destination


async def stream_pocket_tts(
    text: str,
    *,
    voice: str = "alba",
    language: str = "",
    reference_audio: str | Path | None = None,
    voice_design: str = "",
    speed: float = 1.0,
    chunk_chars: int = 180,
) -> AsyncIterator[Any]:
    """Yield HEVI-owned PCM chunks for low-latency playback."""

    mod = _import_pocket_tts()
    model_cls = getattr(mod, "TTSModel", None) if mod is not None else None
    if model_cls is not None:
        model_config = os.getenv("POCKET_TTS_CONFIG", "").strip()
        model = await asyncio.to_thread(_load_model, model_config, language)
        voice_source = str(reference_audio) if reference_audio else (voice.strip() or "alba")
        if reference_audio and not Path(reference_audio).is_file():
            raise FileNotFoundError(f"Pocket TTS reference audio not found: {reference_audio}")
        state = await asyncio.to_thread(model.get_state_for_audio_prompt, voice_source)
        chunks: queue.Queue[tuple[str, Any]] = queue.Queue()
        sentinel = object()

        def produce() -> None:
            try:
                with _MODEL_LOCK:
                    for chunk in model.generate_audio_stream(
                        state,
                        text,
                        max_tokens=max(1, int(chunk_chars)),
                    ):
                        chunks.put(("chunk", chunk))
            except BaseException as exc:  # propagate provider failures to the async caller
                chunks.put(("error", exc))
            finally:
                chunks.put(("done", sentinel))

        threading.Thread(target=produce, name="hevi-pocket-tts-stream", daemon=True).start()
        while True:
            kind, value = await asyncio.to_thread(chunks.get)
            if kind == "error":
                raise value
            if kind == "done":
                break
            yield value
        return

    from hevi.voicepro.oskill import stream_native_voice

    async for chunk in stream_native_voice(
        text,
        voice=voice,
        language=language,
        reference_audio=reference_audio,
        voice_design=voice_design,
        speed=speed,
        chunk_chars=chunk_chars,
    ):
        yield chunk


__all__ = ["pocket_tts_available", "stream_pocket_tts", "synth_with_pocket_tts"]
