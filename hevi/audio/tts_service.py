"""hevi TTS service — delegates to oprim.vibevoice_synthesize (M3 fixed in v3.10.10)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from oprim import vibevoice_synthesize

from hevi.audio.audio_config import AudioProvider
from hevi.gpu import VRAM_VIBEVOICE, scheduler
from hevi.observability import track_provider_call

# vibevoice_synthesize is imported at module level so tests can patch
# hevi.audio.tts_service.vibevoice_synthesize
__all__ = ["synthesize_dialogue", "vibevoice_synthesize"]


async def synthesize_dialogue(
    *,
    config: Any,
    script: list[Any],
    output_path: Path,
    watermark: bool = True,
) -> Path:
    """Multi-speaker TTS — delegates to oprim.vibevoice_synthesize (v3.10.10)."""
    if not script:
        raise ValueError("Script cannot be empty")

    async with scheduler.acquire(VRAM_VIBEVOICE):
        async with track_provider_call(AudioProvider.VIBEVOICE):
            result = await vibevoice_synthesize(
                config=config if isinstance(config, dict) else None,
                script=script,
                output_path=output_path,
                watermark=watermark,
            )
            return Path(result)
