"""Transport-independent realtime voice pipeline primitives."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

TRANSPORTS = ("websocket", "webrtc", "local")
STAGE_KINDS = ("input", "stt", "llm", "tts", "sink", "sidecar")


@dataclass(frozen=True)
class VoiceStage:
    stage_id: str
    kind: str
    engine: str
    optional: bool = False
    config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VoiceAgentRequest:
    prompt: str = ""
    transport: str = "websocket"
    stages: tuple[VoiceStage, ...] = ()
    handoff_targets: tuple[str, ...] = ()
    fanout_targets: tuple[str, ...] = ()
    hold_to_speak: bool = False
    paste_transcript: bool = False
    language: str = "zh"

    def validate(self) -> list[str]:
        issues: list[str] = []
        if self.transport not in TRANSPORTS:
            issues.append(f"unsupported transport: {self.transport}")
        if not self.stages:
            issues.append("at least one pipeline stage is required")
        ids: set[str] = set()
        for stage in self.stages:
            if stage.stage_id in ids:
                issues.append(f"duplicate stage id: {stage.stage_id}")
            ids.add(stage.stage_id)
            if stage.kind not in STAGE_KINDS:
                issues.append(f"unsupported stage kind: {stage.kind}")
            if not stage.engine.strip():
                issues.append(f"stage engine is required: {stage.stage_id}")
        if self.paste_transcript and self.transport != "local":
            issues.append("desktop transcript paste requires local transport")
        return issues


@dataclass(frozen=True)
class VoicePipeline:
    request: VoiceAgentRequest
    status: str
    stages: tuple[VoiceStage, ...]
    edges: tuple[tuple[str, str], ...]
    capabilities: tuple[str, ...]
    errors: tuple[str, ...] = ()
    provider_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["request"]["stages"] = [stage.to_dict() for stage in self.request.stages]
        body["stages"] = [stage.to_dict() for stage in self.stages]
        body["edges"] = [list(edge) for edge in self.edges]
        body["capabilities"] = list(self.capabilities)
        body["errors"] = list(self.errors)
        return body


__all__ = ["STAGE_KINDS", "TRANSPORTS", "VoiceAgentRequest", "VoicePipeline", "VoiceStage"]
