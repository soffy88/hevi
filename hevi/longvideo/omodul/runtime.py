"""LongLive-compatible plan boundary; actual weights stay in a provider."""

from __future__ import annotations

import os
from typing import Any

from hevi.longvideo.oprim.contracts import LongVideoRequest
from hevi.longvideo.oskill.compiler import normalize_shot_prompts


def compile_longvideo_plan(request: LongVideoRequest) -> dict[str, Any]:
    errors = request.validate()
    provider = os.getenv("LONGLIVE_BASE_URL", "").strip() or None
    shots = normalize_shot_prompts(request.shot_prompts)
    if request.mode == "multi_shot" and not shots:
        errors.append("multi_shot requires non-empty shot_prompts")
    status = "blocked" if errors else ("available" if provider else "planned")
    return {
        "status": status,
        "request": request.to_dict(),
        "provider_url": provider,
        "shots": shots,
        "runtime": {
            "parallel": request.sequence_parallel,
            "attention_sink": request.attention_sink,
            "async_decode": request.async_decode,
            "precision": request.precision,
        },
        "errors": errors or ([] if provider else ["no LongLive provider configured; plan only"]),
        "handoff": "longlive-compatible provider" if provider else None,
    }


def longvideo_capabilities() -> dict[str, Any]:
    provider = os.getenv("LONGLIVE_BASE_URL", "").strip() or None
    return {
        "id": "longvideo_generation",
        "available": bool(provider),
        "status": "available" if provider else "unavailable",
        "modes": ["t2v", "i2v", "multi_shot"],
        "features": ["long_context", "attention_sink", "sequence_parallel", "async_decode", "nvfp4_profile"],
        "provider_url": provider,
        "setup": "配置 LONGLIVE_BASE_URL 指向 LongLive-compatible inference provider。",
    }


__all__ = ["compile_longvideo_plan", "longvideo_capabilities"]
