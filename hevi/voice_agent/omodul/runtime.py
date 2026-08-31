"""Realtime voice orchestration boundary; provider execution stays optional."""

from __future__ import annotations

import os
import sys
from itertools import pairwise
from typing import Any

from hevi.voice_agent.oprim.contracts import VoiceAgentRequest, VoicePipeline, VoiceStage


def _edges(stages: tuple[VoiceStage, ...]) -> tuple[tuple[str, str], ...]:
    return tuple((left.stage_id, right.stage_id) for left, right in pairwise(stages))


def compile_voice_pipeline(request: VoiceAgentRequest) -> VoicePipeline:
    errors = request.validate()
    provider_url = os.getenv("VOICE_AGENT_WS_URL", "").strip() or None
    capabilities = ["streaming", "partial_transcript", "stage_handoff", "fanout"]
    if request.hold_to_speak:
        capabilities.append("hold_to_speak")
    if request.paste_transcript:
        if sys.platform == "darwin" and request.transport == "local":
            capabilities.append("desktop_paste")
        else:
            errors.append("desktop paste is only executable on macOS with local transport")
    if request.handoff_targets:
        capabilities.append("agent_handoff")
    return VoicePipeline(
        request=request,
        status="blocked" if errors else ("available" if provider_url else "planned"),
        stages=request.stages,
        edges=_edges(request.stages),
        capabilities=tuple(capabilities),
        errors=tuple(errors) if errors else (() if provider_url else ("no realtime provider configured; pipeline plan only",)),
        provider_url=provider_url,
    )


def voice_agent_capabilities() -> dict[str, Any]:
    provider = os.getenv("VOICE_AGENT_WS_URL", "").strip() or None
    return {
        "id": "voice_agent_realtime",
        "available": bool(provider),
        "status": "available" if provider else "unavailable",
        "transports": ["websocket", "webrtc", "local"],
        "stages": ["input", "stt", "llm", "tts", "sink", "sidecar"],
        "features": ["partial_transcript", "streaming_tts", "handoff", "fanout", "hold_to_speak"],
        "provider_url": provider,
        "setup": "配置 VOICE_AGENT_WS_URL 指向兼容的实时语音 pipeline provider。",
    }


__all__ = ["compile_voice_pipeline", "voice_agent_capabilities"]
