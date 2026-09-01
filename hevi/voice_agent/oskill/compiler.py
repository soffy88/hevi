"""Compile concise voice-agent intents into explicit stages and controls."""

from __future__ import annotations

from hevi.voice_agent.oprim.contracts import VoiceAgentRequest, VoiceStage


def default_voice_request(*, language: str = "zh", transport: str = "websocket") -> VoiceAgentRequest:
    return VoiceAgentRequest(
        transport=transport,
        language=language,
        stages=(
            VoiceStage("mic", "input", "microphone"),
            VoiceStage("transcribe", "stt", "faster_whisper"),
            VoiceStage("reason", "llm", "hevi"),
            VoiceStage("speak", "tts", "edge_tts"),
            VoiceStage("client", "sink", "realtime_client"),
        ),
    )


def natural_language_voice_request(
    instruction: str,
    *,
    language: str = "zh",
    transport: str = "websocket",
) -> VoiceAgentRequest:
    text = instruction.lower()
    base = default_voice_request(language=language, transport=transport)
    stages = list(base.stages)
    if "voicebox" in text:
        stages[3] = VoiceStage("speak", "tts", "voicebox")
    elif "clone" in text or "克隆" in instruction:
        stages[3] = VoiceStage("speak", "tts", "voice_clone")
    if "pipecat" in text or "multi-agent" in text or "多智能体" in instruction:
        stages.append(VoiceStage("orchestrator", "sidecar", "multi_agent_router"))
    hold = any(term in text or term in instruction for term in ("hold", "按住", "按键说话"))
    paste = any(term in text or term in instruction for term in ("paste", "粘贴", "听写"))
    return VoiceAgentRequest(
        prompt=instruction,
        transport=transport,
        stages=tuple(stages),
        hold_to_speak=hold,
        paste_transcript=paste,
        language=language,
    )


__all__ = ["default_voice_request", "natural_language_voice_request"]
