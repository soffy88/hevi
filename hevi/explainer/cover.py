"""Cover extraction boundary for Explainer Master v8 step 10."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


async def cover_extract_and_render(
    video_path: Path,
    output_path: Path,
    *,
    title: str = "",
    extractor: Any = None,
) -> dict[str, Any]:
    """Extract a verified highlight frame; title rendering is provider-injected.

    Returns explicit extractor provenance (requested/actual/substituted) so the
    HEVI-local fallback is never a silent production path.
    """
    requested_extractor = "oprim"
    actual_extractor = "oprim"
    substituted = False
    fallback_reason: str | None = None

    if extractor is None:
        try:
            from oprim import cover_extract_and_render as _oprim_extractor

            extractor = _oprim_extractor
        except ImportError as exc:
            from hevi.assembly.cover_extractor import extract_cover

            extractor = extract_cover
            actual_extractor = "hevi_local"
            substituted = True
            fallback_reason = f"oprim_unavailable:{exc}"
            logger.warning(
                "oprim.cover_extract_and_render unavailable; using hevi.assembly.cover_extractor"
            )
    else:
        requested_extractor = "injected"
        actual_extractor = "injected"

    try:
        result = extractor(video_path, output_path)
        if hasattr(result, "__await__"):
            result = await result
        path = Path(result or output_path)
        if not path.is_file() or path.stat().st_size == 0:
            envelope: dict[str, Any] = {
                "status": "failed",
                "error": f"cover artifact missing: {path}",
            }
        else:
            envelope = {
                "status": "succeeded",
                "path": str(path),
                "title": title,
                "media_type": "image/jpeg",
            }
    except Exception as exc:
        envelope = {"status": "failed", "error": str(exc)}

    envelope.update(
        {
            "requested_extractor": requested_extractor,
            "actual_extractor": actual_extractor,
            "extractor_substituted": substituted,
        }
    )
    if fallback_reason is not None:
        envelope["fallback_reason"] = fallback_reason
    return envelope
