"""Shared vibevoice top-level export patch — applied by both the main process
(hevi.providers.registry.register_all_providers) and vibevoice_worker.py.

vibevoice PyPI 0.0.1 (the only release published) ships an empty top-level
__init__.py — the classes oprim._vibevoice_synthesize needs only exist in
submodules, so `from vibevoice import VibeVoiceForConditionalGenerationInference,
VibeVoiceProcessor` fails unless this patch has run in the *current process*.
It must run in vibevoice_worker.py too, not just the main process: the worker
is a fresh subprocess (for VRAM isolation) that does not inherit the main
process's already-patched module object — every real TTS call was hitting
"vibevoice package not installed" until this was applied there as well.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def patch_vibevoice_exports() -> None:
    try:
        import vibevoice
        from vibevoice.modular.modeling_vibevoice_inference import (
            VibeVoiceForConditionalGenerationInference,
        )
        from vibevoice.processor.vibevoice_processor import VibeVoiceProcessor

        vibevoice.VibeVoiceForConditionalGenerationInference = (
            VibeVoiceForConditionalGenerationInference
        )
        vibevoice.VibeVoiceProcessor = VibeVoiceProcessor
        logger.info("Main library bug patched: vibevoice top-level exports (empty __init__.py)")
    except Exception as e:
        logger.error(f"Failed to patch vibevoice exports: {e}")


def patch_vibevoice_reference_audio_kwarg() -> None:
    """oprim._vibevoice_synthesize._infer() calls
    `processor(text=..., return_tensors="pt", reference_audio=<path>)` when a voice_ref
    is given. This vibevoice release's `VibeVoiceProcessor.__call__` has no
    `reference_audio` parameter — it's a real keyword arg named `voice_samples`
    (list of path/ndarray). An unrecognized kwarg is silently absorbed into the
    method's `**kwargs` and dropped, so `voice_samples` stays `None` and the
    processor emits `speech_tensors=None` — which `model.generate()` unconditionally
    calls `.to(device)` on, crashing with `AttributeError: 'NoneType' object has no
    attribute 'to'`. This reproduced identically whether or not a voice_ref was
    supplied, which is what pointed at a kwarg-name mismatch rather than "no
    reference provided" (this vibevoice release has no default/reference-free
    voice — a voice_samples entry is required for every call, always).

    Wraps `__call__` to translate `reference_audio=` into `voice_samples=[...]`
    transparently, so oprim's code works without waiting on an upstream oprim fix.
    """
    from vibevoice.processor.vibevoice_processor import VibeVoiceProcessor

    if getattr(VibeVoiceProcessor.__call__, "_hevi_patched", False):
        return

    original_call = VibeVoiceProcessor.__call__

    def _patched_call(self, *args, **kwargs):
        reference_audio = kwargs.pop("reference_audio", None)
        if reference_audio is not None and kwargs.get("voice_samples") is None:
            kwargs["voice_samples"] = [reference_audio]
        return original_call(self, *args, **kwargs)

    _patched_call._hevi_patched = True
    VibeVoiceProcessor.__call__ = _patched_call
    logger.info("Main library bug patched: vibevoice reference_audio -> voice_samples kwarg")
