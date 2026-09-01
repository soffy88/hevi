"""JoyAI-compatible causal video-to-video streaming routes."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.joyai.omodul.stream_edit import (
    capabilities,
    create_session,
    finish_session,
    get_session,
    list_sessions,
    record_frame,
    record_output,
    start_session,
    stream_provider_url,
)
from hevi.joyai.oprim.stream_contract import frame_budget, validate_control
from hevi.provider_policy.runtime import probe_provider

router = APIRouter(prefix="/stream-edit", tags=["stream-edit"])


class StreamEditCreateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=10_000)
    source_mode: str = Field(default="live", pattern="^(live|upload)$")
    width: int = Field(default=840, ge=160, le=2048)
    height: int = Field(default=480, ge=160, le=2048)
    fps: int = Field(default=24, ge=1, le=60)
    model: str = Field(default="joyai-video-edit", min_length=1)
    reference_images: list[str] = Field(default_factory=list, max_length=8)
    low_vram: bool = False


@router.get("/capabilities")
async def stream_capabilities() -> dict[str, Any]:
    catalog = capabilities()
    provider_status = await probe_provider("joyai", timeout_s=3.0)
    catalog["provider_runtime"] = provider_status
    catalog["available"] = bool(provider_status["ready"])
    catalog["status"] = "available" if provider_status["ready"] else "unavailable"
    return catalog


@router.get("/budget")
async def stream_budget(
    width: int = 840,
    height: int = 480,
    fps: int = 24,
    seconds: float = 1.0,
) -> dict[str, Any]:
    if not 160 <= width <= 2048 or not 160 <= height <= 2048 or not 1 <= fps <= 60:
        raise HTTPException(status_code=422, detail="width/height/fps 超出实时帧预算边界")
    return frame_budget(width=width, height=height, fps=fps, seconds=seconds)


@router.get("/sessions")
async def sessions(_: Annotated[dict[str, Any], Depends(get_current_user)]) -> dict[str, Any]:
    items = [item.to_dict() for item in list_sessions()]
    return {"sessions": items, "total": len(items)}


@router.post("/sessions", status_code=201)
async def create_stream_session(
    body: StreamEditCreateRequest,
    _: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    provider_status = await probe_provider("joyai", timeout_s=3.0)
    session = create_session(**body.model_dump())
    if not provider_status["ready"]:
        session.status = "blocked"
        session.last_error = f"JoyAI provider unavailable: {provider_status.get('error')}"
        session.decision_trail.append("provider health probe failed")
    return session.to_dict()


@router.get("/sessions/{session_id}")
async def stream_session(
    session_id: str,
    _: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="stream session not found")
    return session.to_dict()


@router.post("/sessions/{session_id}/finish")
async def finish_stream_session(
    session_id: str,
    _: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    session = finish_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="stream session not found")
    return session.to_dict()


async def _send_provider_error(websocket: WebSocket, code: str, message: str) -> None:
    await websocket.send_json({"type": "error", "code": code, "message": message})
    await websocket.close(code=1011)


@router.websocket("/sessions/{session_id}/stream")
async def stream_socket(websocket: WebSocket, session_id: str) -> None:
    """Bidirectionally proxy source frames and edited frames.

    HEVI owns the client-facing protocol and counters.  It forwards binary
    frames unchanged, so no intermediate placeholder or lossy re-encode is
    introduced in the HEVI process.
    """

    await websocket.accept()
    session = get_session(session_id)
    if session is None:
        await _send_provider_error(websocket, "STREAM_SESSION_NOT_FOUND", "stream session not found")
        return
    if session.status == "blocked":
        await _send_provider_error(
            websocket,
            "JOYAI_PROVIDER_UNAVAILABLE",
            session.last_error or "JoyAI provider unavailable",
        )
        return
    provider = stream_provider_url()
    if not provider:
        await _send_provider_error(
            websocket,
            "JOYAI_PROVIDER_UNAVAILABLE",
            "JOYAI_STREAM_WS_URL/JOYAI_BASE_URL 未配置",
        )
        finish_session(session_id, error="JoyAI provider URL missing")
        return

    try:
        from websockets.asyncio.client import connect

        async with connect(provider, open_timeout=10, ping_interval=20) as upstream:
            start_session(session_id)
            await upstream.send(json.dumps({"type": "start", **session.request.to_dict()}))

            async def client_to_provider() -> None:
                while True:
                    message = await websocket.receive()
                    if message.get("type") == "websocket.disconnect":
                        return
                    if message.get("bytes") is not None:
                        record_frame(session_id)
                        await upstream.send(message["bytes"])
                        continue
                    raw = message.get("text") or ""
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        await websocket.send_json(
                            {"type": "error", "code": "INVALID_STREAM_JSON", "message": "控制消息必须是 JSON"}
                        )
                        continue
                    if not isinstance(payload, dict):
                        await websocket.send_json(
                            {"type": "error", "code": "INVALID_STREAM_CONTROL", "message": "控制消息必须是 object"}
                        )
                        continue
                    errors = validate_control(payload)
                    if errors:
                        await websocket.send_json(
                            {"type": "error", "code": "INVALID_STREAM_CONTROL", "errors": errors}
                        )
                        continue
                    if payload.get("type") == "end":
                        await upstream.send(raw)
                        finish_session(session_id)
                        return
                    await upstream.send(raw)

            async def provider_to_client() -> None:
                while True:
                    response = await upstream.recv()
                    if isinstance(response, bytes):
                        record_output(session_id)
                        await websocket.send_bytes(response)
                    else:
                        await websocket.send_text(response)

            client_task = asyncio.create_task(client_to_provider())
            provider_task = asyncio.create_task(provider_to_client())
            done, pending = await asyncio.wait(
                (client_task, provider_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                exception = task.exception()
                if exception and not isinstance(exception, WebSocketDisconnect):
                    raise exception
    except WebSocketDisconnect:
        finish_session(session_id, error="client disconnected")
    except Exception as exc:
        finish_session(session_id, error=str(exc)[:500])
        with suppress(Exception):
            await _send_provider_error(websocket, "JOYAI_STREAM_FAILED", str(exc)[:300])
    else:
        current = get_session(session_id)
        if current is not None and current.status == "running":
            finish_session(session_id)


__all__ = ["router"]
