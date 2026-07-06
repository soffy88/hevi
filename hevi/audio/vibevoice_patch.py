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
