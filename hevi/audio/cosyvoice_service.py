"""CosyVoice TTS service wrapper.

Provides a function `cosyvoice_synthesize` that forwards to the existing
`vibevoice_synthesize` implementation but respects the CosyVoice configuration
settings defined in `hevi.core.config.Settings`.
"""

from __future__ import annotations

import inspect
import os
from pathlib import Path
from typing import Any

from hevi.audio.tts_service import vibevoice_synthesize
from hevi.core.config import settings

__all__ = ["cosyvoice_synthesize"]


async def cosyvoice_synthesize(
    *,
    config: dict[str, Any] | None = None,
    script: list[Any],
    output_path: Path,
    watermark: bool = True,
) -> Path:
    """CosyVoice TTS synthesis.

    This wrapper mirrors :func:`vibevoice_synthesize` but uses the CosyVoice
    configuration values (model directory and watermark flag) defined in the
    global settings. It ultimately re‑uses the existing ``vibevoice_synthesize``
    implementation which runs the synthesis in an isolated subprocess.
    """
    cfg = config or {}
    # Prefer explicit config, then fall back to global settings.
    model_dir = (
        cfg.get("COSYVOICE_MODEL_DIR")
        or getattr(settings, "cosyvoice_model_dir", None)
        or os.getenv("COSYVOICE_MODEL_DIR")
        or "/opt/cosyvoice/model"
    )
    use_watermark = (
        cfg.get("COSYVOICE_USE_WATERMARK")
        if cfg.get("COSYVOICE_USE_WATERMARK") is not None
        else getattr(settings, "cosyvoice_use_watermark", True)
    )
    # Use the public CosyVoice primitive when the installed oprim exposes it.
    # Older deployments fall back to the existing isolated local worker; they
    # still return a verified file or raise a provider error.
    try:
        import oprim

        provider = getattr(oprim, "cosyvoice_tts_call", None)
    except ImportError:
        provider = None
    if provider is not None:
        result = provider(
            config={"COSYVOICE_MODEL_DIR": model_dir},
            script=script,
            output_path=output_path,
            watermark=bool(use_watermark),
        )
        if inspect.isawaitable(result):
            result = await result
        path = Path(result or output_path)
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"CosyVoice 未产出音频文件: {path}")
        return path
    return await vibevoice_synthesize(
        config={"VIBEVOICE_MODEL_DIR": model_dir},
        script=script,
        output_path=output_path,
        watermark=bool(use_watermark),
    )
