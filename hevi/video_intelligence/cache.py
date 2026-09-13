"""Content-addressed cache keys for deterministic machine analysis."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import VIDEO_INTELLIGENCE_CONTRACT_VERSION


def analysis_cache_key(
    source_sha256: str,
    config: dict[str, Any],
    *,
    detector_version: str = "ffmpeg-scene-v1",
    semantic_provider: str | None = None,
    semantic_model: str | None = None,
) -> str:
    payload = {
        "source_sha256": source_sha256,
        "contract_version": VIDEO_INTELLIGENCE_CONTRACT_VERSION,
        "detector_version": detector_version,
        "config": config,
        "semantic_provider": semantic_provider,
        "semantic_model": semantic_model,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
