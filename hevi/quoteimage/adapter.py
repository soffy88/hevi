from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.quoteimage.omodul_impl.produce import produce_quote_image

async def render_quote_image(
    video_path: Path | str,
    mode: str,
    strategy: str,
    output_dir: Path | str,
    **kwargs: Any,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        produce_quote_image,
        video_path=Path(video_path),
        mode=mode,
        strategy=strategy,
        output_dir=Path(output_dir),
        **kwargs
    )
