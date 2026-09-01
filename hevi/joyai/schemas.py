"""obase contracts for causal streaming video-to-video editing."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class StreamEditRequest:
    prompt: str
    source_mode: str = "live"
    width: int = 840
    height: int = 480
    fps: int = 24
    model: str = "joyai-video-edit"
    reference_images: tuple[str, ...] = ()
    low_vram: bool = False

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["reference_images"] = list(self.reference_images)
        return body


@dataclass
class StreamEditSession:
    session_id: str
    request: StreamEditRequest
    status: str = "created"
    input_frames: int = 0
    output_frames: int = 0
    started_at: str = ""
    ended_at: str = ""
    last_error: str | None = None
    decision_trail: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "request": self.request.to_dict(),
            "status": self.status,
            "input_frames": self.input_frames,
            "output_frames": self.output_frames,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "last_error": self.last_error,
            "decision_trail": list(self.decision_trail),
        }


__all__ = ["StreamEditRequest", "StreamEditSession"]
