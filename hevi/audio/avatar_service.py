"""hevi.audio.avatar_service — delegates to oprim.avatar_generate (M4 fixed in v3.10.8)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from oprim import avatar_generate

from hevi.audio.audio_config import AudioProvider
from hevi.gpu import VRAM_DUIX, scheduler
from hevi.observability import track_provider_call

# avatar_generate is imported at module level so tests can patch
# hevi.audio.avatar_service.avatar_generate
__all__ = ["generate_avatar_clip", "avatar_generate"]


async def generate_avatar_clip(
    *,
    config: Any,
    portrait_image: Path,
    audio_path: Path,
    output_path: Path,
) -> Path:
    """Duix digital human avatar clip generation — delegates to oprim.avatar_generate."""
    async with scheduler.acquire(VRAM_DUIX):
        async with track_provider_call(AudioProvider.DUIX):
            result = await avatar_generate(
                provider=str(AudioProvider.DUIX),
                portrait_image=portrait_image,
                audio_path=audio_path,
                output_path=output_path,
            )
            return Path(result)
