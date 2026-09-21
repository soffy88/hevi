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

import importlib
import importlib.metadata
import logging
import sys
import types
from typing import Any

logger = logging.getLogger(__name__)


class VibeVoiceCompatibilityError(RuntimeError):
    """The installed VibeVoice/Transformers pair is outside the tested seam."""


def _ensure_vibevoice_transformers_compat() -> None:
    """Provide the legacy Qwen2 fast-tokenizer import expected by vibevoice.

    Transformers 5.x exposes the Qwen2 tokenizer through its lazy package but
    no longer ships the old ``tokenization_qwen2_fast`` module.  vibevoice
    0.0.1 imports that module directly.  The current tokenizer backend is the
    compatible implementation for this package, so install a process-local
    import shim only when the legacy module is absent.
    """
    module_name = "transformers.models.qwen2.tokenization_qwen2_fast"
    if module_name in sys.modules:
        return
    try:
        importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
        from transformers.models.qwen2.tokenization_qwen2 import Qwen2Tokenizer

        compat_module = types.ModuleType(module_name)
        compat_module.Qwen2TokenizerFast = Qwen2Tokenizer  # type: ignore[attr-defined]
        sys.modules[module_name] = compat_module


def patch_vibevoice_exports() -> None:
    """Expose the two classes even with Transformers' VibeVoice mappings.

    vibevoice 0.0.1 registers its tokenizer models at import time.  Recent
    Transformers releases already ship mappings with the same model types, so
    the upstream registration raises before the package's model module finishes
    importing.  Allow only these two known third-party registrations to use
    ``exist_ok`` while importing, then restore the mapping method immediately.
    This keeps the compatibility scope narrow and makes repeated process
    initialization idempotent.
    """
    try:
        transformers_version = importlib.metadata.version("transformers")
        vibevoice_version = importlib.metadata.version("vibevoice")
    except importlib.metadata.PackageNotFoundError as exc:
        raise VibeVoiceCompatibilityError(
            f"VibeVoice compatibility guard cannot resolve installed package: {exc}"
        ) from exc
    if not transformers_version.startswith("5.") or vibevoice_version != "0.0.1":
        raise VibeVoiceCompatibilityError(
            "unsupported VibeVoice compatibility pair: "
            f"transformers={transformers_version}, vibevoice={vibevoice_version}; "
            "tested pair is transformers 5.x + vibevoice 0.0.1"
        )

    vibevoice = sys.modules.get("vibevoice")
    if vibevoice is not None and all(
        hasattr(vibevoice, name)
        for name in ("VibeVoiceForConditionalGenerationInference", "VibeVoiceProcessor")
    ):
        return

    from transformers.models.auto import AutoModel, AutoModelForCausalLM

    _ensure_vibevoice_transformers_compat()
    mappings = [AutoModel._model_mapping, AutoModelForCausalLM._model_mapping]
    originals = [mapping.register for mapping in mappings]

    def _is_vibevoice_config(key: Any) -> bool:
        module = str(getattr(key, "__module__", ""))
        return module.startswith("vibevoice.") and str(getattr(key, "__name__", "")).startswith("VibeVoice")

    def _make_register_compat(original: Any) -> Any:
        def _register_compat(key: Any, value: Any, exist_ok: bool = False) -> None:
            # Only VibeVoice's own config classes receive idempotent registration;
            # every unrelated Transformers registration retains upstream semantics.
            original(key, value, exist_ok=True if _is_vibevoice_config(key) else exist_ok)

        return _register_compat

    for mapping, original in zip(mappings, originals, strict=True):
        mapping.register = _make_register_compat(original)  # type: ignore[method-assign]
    try:
        importlib.import_module("vibevoice")
        from vibevoice.modular.modeling_vibevoice_inference import (
            VibeVoiceForConditionalGenerationInference,
        )
        from vibevoice.processor.vibevoice_processor import VibeVoiceProcessor
    finally:
        for mapping, original in zip(mappings, originals, strict=True):
            mapping.register = original  # type: ignore[method-assign]

    vibevoice_module: Any = sys.modules["vibevoice"]
    vibevoice_module.VibeVoiceForConditionalGenerationInference = (
        VibeVoiceForConditionalGenerationInference
    )
    vibevoice_module.VibeVoiceProcessor = VibeVoiceProcessor
    logger.info("VibeVoice compatibility registration seam initialized")


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

    def _patched_call(self: Any, *args: Any, **kwargs: Any) -> Any:
        reference_audio = kwargs.pop("reference_audio", None)
        if reference_audio is not None and kwargs.get("voice_samples") is None:
            kwargs["voice_samples"] = [reference_audio]
        return original_call(self, *args, **kwargs)

    VibeVoiceProcessor.__call__ = _patched_call
    logger.info("Main library bug patched: vibevoice reference_audio -> voice_samples kwarg")
