"""hevi.audio.avatar_service — delegates to oprim.avatar_generate."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from oprim import avatar_generate

from hevi.audio.audio_config import AudioProvider
from hevi.gpu import VRAM_DUIX, scheduler
from hevi.observability import track_provider_call

# avatar_generate is imported at module level so tests can patch
# hevi.audio.avatar_service.avatar_generate
__all__ = ["avatar_generate", "generate_avatar_clip"]

_DUIX_CFG_KEYS = ("DUIX_HOST_DATA_DIR", "DUIX_CONTAINER_DATA_DIR")


async def generate_avatar_clip(
    *,
    config: Any,
    portrait_image: Path,
    audio_path: Path,
    output_path: Path,
) -> Path:
    """Duix digital human avatar clip generation — delegates to oprim.avatar_generate.

    config dict keys forwarded to oprim._config (via os.environ):
        DUIX_HOST_DATA_DIR      host-side bind-mount root
        DUIX_CONTAINER_DATA_DIR container-side mount point (default /code/data)
    """
    if isinstance(config, dict):
        for key in _DUIX_CFG_KEYS:
            if val := config.get(key):
                os.environ[key] = str(val)
    async with scheduler.acquire(VRAM_DUIX), track_provider_call(AudioProvider.DUIX):
        result = await avatar_generate(
            provider=str(AudioProvider.DUIX),
            portrait_image=portrait_image,
            audio_path=audio_path,
            output_path=output_path,
        )
        return Path(result)
