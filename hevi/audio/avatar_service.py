from pathlib import Path
from typing import Any

from oprim import avatar_generate


async def generate_avatar_clip(
    *,
    config: Any,
    portrait_image: Path,
    audio_path: Path,
    output_path: Path,
) -> Path:
    """Duix digital human avatar clip generation (lip-sync)."""
    return await avatar_generate(  # type: ignore[no-any-return, operator]
        config=config,
        provider="duix",
        portrait_image=portrait_image,
        audio_path=audio_path,
        output_path=output_path,
    )
