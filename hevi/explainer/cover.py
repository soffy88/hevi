"""Cover extraction boundary for Explainer Master v8 step 10."""

from __future__ import annotations

from pathlib import Path
from typing import Any


async def cover_extract_and_render(
    video_path: Path,
    output_path: Path,
    *,
    title: str = "",
    extractor: Any = None,
) -> dict[str, Any]:
    """Extract a verified highlight frame; title rendering is provider-injected."""
    if extractor is None:
        try:
            from oprim import cover_extract_and_render as _oprim_extractor

            extractor = _oprim_extractor
        except ImportError:
            from hevi.assembly.cover_extractor import extract_cover

            extractor = extract_cover
    try:
        result = extractor(video_path, output_path)
        if hasattr(result, "__await__"):
            result = await result
        path = Path(result or output_path)
        if not path.is_file() or path.stat().st_size == 0:
            return {"status": "failed", "error": f"cover artifact missing: {path}"}
        return {
            "status": "succeeded",
            "path": str(path),
            "title": title,
            "media_type": "image/jpeg",
        }
    except Exception as exc:
        return {"status": "failed", "error": str(exc)}
