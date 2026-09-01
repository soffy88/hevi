"""Causal streaming V2V session workflow.

The workflow owns session state and the 3O decision trail.  A configured
JoyAI-compatible WebSocket provider is required for actual frame editing;
HEVI never emits a placeholder edited frame when the provider is absent.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hevi.joyai.oprim.stream_contract import frame_budget
from hevi.joyai.schemas import StreamEditRequest, StreamEditSession

_SESSIONS: dict[str, StreamEditSession] = {}


def provider_url() -> str:
    return (os.getenv("JOYAI_STREAM_WS_URL") or os.getenv("JOYAI_BASE_URL") or "").strip().rstrip("/")


def stream_provider_url() -> str:
    """Resolve an explicit WebSocket endpoint from a base or stream URL."""

    explicit = os.getenv("JOYAI_STREAM_WS_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    base = os.getenv("JOYAI_BASE_URL", "").strip().rstrip("/")
    if not base:
        return ""
    if base.startswith("https://"):
        base = "wss://" + base.removeprefix("https://")
    elif base.startswith("http://"):
        base = "ws://" + base.removeprefix("http://")
    path = os.getenv("JOYAI_STREAM_WS_PATH", "/ws/edit").strip() or "/ws/edit"
    return f"{base}/{path.lstrip('/')}"


def provider_available() -> bool:
    return bool(stream_provider_url())


def create_session(
    *,
    prompt: str,
    source_mode: str = "live",
    width: int = 840,
    height: int = 480,
    fps: int = 24,
    model: str = "joyai-video-edit",
    reference_images: list[str] | None = None,
    low_vram: bool = False,
) -> StreamEditSession:
    refs = tuple(str(Path(item).expanduser()) for item in (reference_images or []))
    missing = [item for item in refs if not Path(item).is_file()]
    request = StreamEditRequest(
        prompt=prompt.strip(),
        source_mode=source_mode,
        width=max(160, min(width, 2048)),
        height=max(160, min(height, 2048)),
        fps=max(1, min(fps, 60)),
        model=model,
        reference_images=refs,
        low_vram=low_vram,
    )
    session = StreamEditSession(
        session_id=f"joyai-{uuid.uuid4().hex[:12]}",
        request=request,
        status="ready" if provider_available() and not missing else "blocked",
        decision_trail=[
            "causal frame protocol selected",
            "reference image paths are local-only",
            "provider configured"
            if provider_available()
            else "provider unavailable: JOYAI_STREAM_WS_URL/JOYAI_BASE_URL missing",
        ],
    )
    if missing:
        session.last_error = f"reference image not found: {', '.join(missing)}"
        session.decision_trail.append("session blocked by missing reference image")
    _SESSIONS[session.session_id] = session
    return session


def get_session(session_id: str) -> StreamEditSession | None:
    return _SESSIONS.get(session_id)


def list_sessions() -> list[StreamEditSession]:
    return list(_SESSIONS.values())


def start_session(session_id: str) -> StreamEditSession | None:
    session = get_session(session_id)
    if session is None:
        return None
    if session.status == "blocked":
        return session
    session.status = "running"
    session.started_at = datetime.now(UTC).isoformat()
    return session


def record_frame(session_id: str, *, output: bool = False) -> StreamEditSession | None:
    session = get_session(session_id)
    if session is None:
        return None
    if output:
        session.output_frames += 1
    else:
        session.input_frames += 1
    return session


def record_output(session_id: str) -> StreamEditSession | None:
    return record_frame(session_id, output=True)


def finish_session(session_id: str, *, error: str | None = None) -> StreamEditSession | None:
    session = get_session(session_id)
    if session is None:
        return None
    session.status = "failed" if error else "completed"
    session.last_error = error
    session.ended_at = datetime.now(UTC).isoformat()
    return session


def capabilities() -> dict[str, Any]:
    return {
        "id": "streaming_v2v",
        "available": provider_available(),
        "status": "available" if provider_available() else "unavailable",
        "modes": ["live", "upload"],
        "controls": ["subject_edit", "local_edit", "background_change", "style_transfer", "motion_change", "reference_image"],
        "transport": "websocket",
        "causal": True,
        "open_ended": True,
        "frame_budget": frame_budget(width=840, height=480, fps=24),
        "setup": "配置 JOYAI_STREAM_WS_URL（或 JOYAI_BASE_URL）并启动 JoyAI-compatible streaming provider。",
        "provider_url": stream_provider_url() or None,
        "notes": [
            "没有 provider 时只允许创建 blocked session，不产生伪造视频帧。",
            "重型模型权重与 CUDA runtime 由 provider 负责，HEVI 负责会话、审计和产物边界。",
        ],
    }


def reset_sessions() -> None:
    _SESSIONS.clear()


__all__ = [
    "capabilities",
    "create_session",
    "finish_session",
    "get_session",
    "list_sessions",
    "provider_available",
    "provider_url",
    "record_frame",
    "record_output",
    "reset_sessions",
    "start_session",
    "stream_provider_url",
]
