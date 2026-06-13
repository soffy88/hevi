from pathlib import Path
from typing import Any

from oprim import avatar_generate

from hevi.audio.audio_config import AudioProvider
from hevi.observability import track_provider_call


async def generate_avatar_clip(
    *,
    config: Any,
    portrait_image: Path,
    audio_path: Path,
    output_path: Path,
) -> Path:
    """Duix digital human avatar clip generation (lip-sync)."""
    async with track_provider_call(AudioProvider.DUIX):
        return await avatar_generate(  # type: ignore[no-any-return]
            config=config,
            provider="duix",
            portrait_image=portrait_image,
            audio_path=audio_path,
            output_path=output_path,
        )
