"""VoiceStudio-compatible platform routes.

The ``/api/voice-studio/platform`` routes expose HEVI's model/gallery and
workflow contracts.  The ``/v1`` routes provide an authenticated local
OpenAI-compatible audio façade for agents and desktop clients.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, WebSocket
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from hevi.audio.speech_platform import build_batch_plan, get_engine, list_voice_profiles
from hevi.auth.dependencies import get_current_user
from hevi.voicepro.omodul.openai_audio import (
    AUDIO_FORMATS,
    synthesize_audio_file,
    transcribe_audio_file,
)
from hevi.voicepro.omodul.platform import (
    create_voice_profile,
    delete_voice_profile,
    list_gallery_profiles,
    list_model_catalog,
    plan_audiobook,
    plan_dictation,
    plan_dubbing,
    plan_watermark,
    platform_diagnostics,
    register_model,
    route_model,
    unregister_model,
)

router = APIRouter(prefix="/voice-studio/platform", tags=["voice-platform"])
openai_router = APIRouter(prefix="/v1", tags=["voice-platform-openai"])


class ModelRegisterRequest(BaseModel):
    model_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: str = Field(pattern="^(tts|asr|llm)$")
    engine: str = Field(min_length=1)
    path: str = Field(min_length=1)
    device: str = "auto"
    languages: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)


class ModelRouteRequest(BaseModel):
    kind: str = Field(pattern="^(tts|asr|llm)$")
    preferred: str | None = None
    device: str = "auto"


class VoiceProfileRequest(BaseModel):
    name: str = Field(min_length=1)
    engine: str = "cosyvoice"
    reference_audio: str = Field(min_length=1)
    language: str = ""
    reference_text: str = ""
    tags: list[str] = Field(default_factory=list)


class DubbingPlanRequest(BaseModel):
    source_video: str = Field(min_length=1)
    target_language: str = Field(min_length=1)
    preserve_speakers: bool = True
    keep_bed: bool = True
    asr_engine: str = "faster_whisper"
    tts_engine: str = "edge_tts"


class AudiobookPlanRequest(BaseModel):
    source_document: str = Field(min_length=1)
    output_path: str = "output/audiobooks/book.m4b"
    voice_map: dict[str, str] = Field(default_factory=dict)


class DictationPlanRequest(BaseModel):
    language: str = ""
    engine: str = "faster_whisper"


class WatermarkPlanRequest(BaseModel):
    audio_path: str = Field(min_length=1)
    operation: str = "embed"


class BatchRequest(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    execute: bool = False
    output_dir: str = "output/voice-platform/batch"


class OpenAISpeechRequest(BaseModel):
    model: str = "edge_tts"
    input: str = Field(min_length=1, max_length=100_000)
    voice: str = ""
    response_format: str = "wav"
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    language: str = ""
    instructions: str = ""
    reference_audio: str = ""
    reference_text: str = ""
    voice_design: str = ""


@router.get("/models")
async def models(_: Annotated[dict[str, Any], Depends(get_current_user)]) -> dict[str, Any]:
    items = list_model_catalog()
    return {"models": items, "total": len(items)}


@router.post("/models/register")
async def register(body: ModelRegisterRequest, _: Annotated[dict[str, Any], Depends(get_current_user)]) -> dict[str, Any]:
    return register_model(**body.model_dump())


@router.delete("/models/{model_id}")
async def unregister(model_id: str, _: Annotated[dict[str, Any], Depends(get_current_user)]) -> dict[str, Any]:
    return {"model_id": model_id, "removed": unregister_model(model_id)}


@router.post("/route")
async def route(body: ModelRouteRequest, _: Annotated[dict[str, Any], Depends(get_current_user)]) -> dict[str, Any]:
    return route_model(kind=body.kind, preferred=body.preferred, device=body.device)


@router.get("/voices")
async def voices(_: Annotated[dict[str, Any], Depends(get_current_user)]) -> dict[str, Any]:
    """VoiceStudio-compatible voice list, including built-ins and local gallery."""

    builtin = [item.to_dict() for item in list_voice_profiles()]
    gallery_items = list_gallery_profiles()
    return {"voices": [*builtin, *gallery_items], "total": len(builtin) + len(gallery_items)}


@router.get("/voices/gallery")
async def gallery(_: Annotated[dict[str, Any], Depends(get_current_user)]) -> dict[str, Any]:
    items = list_gallery_profiles()
    return {"profiles": items, "total": len(items)}


@router.post("/voices/gallery", status_code=201)
async def create_gallery(
    body: VoiceProfileRequest,
    _: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    try:
        return create_voice_profile(**body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/voices/gallery/{profile_id}")
async def remove_gallery(
    profile_id: str,
    _: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    return {"profile_id": profile_id, "removed": delete_voice_profile(profile_id)}


@router.post("/dubbing/plan")
async def dubbing_plan(
    body: DubbingPlanRequest,
    _: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    return plan_dubbing(**body.model_dump())


@router.post("/audiobook/plan")
async def audiobook_plan(
    body: AudiobookPlanRequest,
    _: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    return plan_audiobook(**body.model_dump())


@router.post("/dictation/plan")
async def dictation_plan(
    body: DictationPlanRequest,
    _: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    return plan_dictation(**body.model_dump())


@router.post("/watermark/plan")
async def watermark_plan(
    body: WatermarkPlanRequest,
    _: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    return plan_watermark(**body.model_dump())


@router.post("/batch")
async def batch(
    body: BatchRequest,
    _: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Validate or execute a local batch, returning one manifest per real file."""

    plan = build_batch_plan(body.items)
    if not body.execute:
        return {**plan, "executed": False}
    results: list[dict[str, Any]] = []
    errors = list(plan["errors"])
    for job in plan["jobs"]:
        if not job["available"]:
            errors.append(f"items[{job['index']}].engine unavailable: {job['engine']}")
            continue
        item = body.items[job["index"]]
        try:
            results.append(
                await synthesize_audio_file(
                    text=job["text"],
                    engine=job["engine"],
                    voice=job["voice"],
                    language=job["language"],
                    response_format=str(item.get("response_format") or "wav"),
                    speed=float(item.get("speed") or 1.0),
                    instructions=str(item.get("instructions") or ""),
                    reference_audio=str(item.get("reference_audio") or ""),
                    reference_text=str(item.get("reference_text") or ""),
                    voice_design=str(item.get("voice_design") or ""),
                    output_dir=body.output_dir,
                )
            )
        except (ValueError, RuntimeError, OSError) as exc:
            errors.append(f"items[{job['index']}]: {exc}")
    return {
        "valid": not errors and bool(results),
        "executed": True,
        "results": results,
        "errors": errors,
    }


@router.get("/diagnostics")
async def diagnostics(_: Annotated[dict[str, Any], Depends(get_current_user)]) -> dict[str, Any]:
    return platform_diagnostics()


@openai_router.get("/.well-known/voicestudio-speech")
async def discovery(_: Annotated[dict[str, Any], Depends(get_current_user)]) -> dict[str, Any]:
    return {
        "name": "hevi-voice-platform",
        "http": "/v1/audio",
        "websocket": "/v1/audio/transcriptions/stream",
        "mcp": "/mcp",
        "formats": sorted(AUDIO_FORMATS),
        "local_first": True,
        "operations": ["speech", "speech_stream", "transcriptions", "voice_catalog", "batch"],
    }


@openai_router.get("/audio/voices")
async def openai_voices(_: Annotated[dict[str, Any], Depends(get_current_user)]) -> dict[str, Any]:
    """Return the OpenAI-compatible voice catalogue without loading models."""

    builtin = [item.to_dict() for item in list_voice_profiles()]
    gallery_items = list_gallery_profiles()
    return {"voices": [*builtin, *gallery_items], "total": len(builtin) + len(gallery_items)}


@openai_router.post("/audio/speech")
async def speech(
    body: OpenAISpeechRequest,
    _: Annotated[dict[str, Any], Depends(get_current_user)],
) -> FileResponse:
    model = body.model
    if model in {"tts-1", "tts-1-hd"}:
        selected = route_model(kind="tts")
        if selected["selected"] is None:
            raise HTTPException(status_code=503, detail="没有可用 TTS 模型")
        model = str(selected["selected"]["engine"])
    try:
        result = await synthesize_audio_file(
            text=body.input,
            engine=model,
            voice=body.voice,
            language=body.language,
            response_format=body.response_format,
            speed=body.speed,
            instructions=body.instructions,
            reference_audio=body.reference_audio,
            reference_text=body.reference_text,
            voice_design=body.voice_design,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return FileResponse(result["path"], media_type=result["media_type"], filename=Path(result["path"]).name)


@openai_router.post("/audio/speech/stream")
async def speech_stream(
    body: OpenAISpeechRequest,
    _: Annotated[dict[str, Any], Depends(get_current_user)],
) -> StreamingResponse:
    """Stream native Pocket/VoxCPM PCM chunks without creating a task first."""

    if body.model == "pocket_tts":
        from hevi.audio.pocket_tts_service import stream_pocket_tts as stream_speech
    elif body.model == "voxcpm":
        from hevi.audio.voxcpm_service import stream_voxcpm as stream_speech
    else:
        raise HTTPException(
            status_code=422,
            detail="streaming speech currently supports pocket_tts and voxcpm",
        )
    engine = get_engine(body.model)
    if engine is None or not engine.available:
        raise HTTPException(status_code=503, detail=f"TTS engine unavailable: {body.model}")

    async def body_stream() -> AsyncIterator[bytes]:
        async for chunk in stream_speech(
            body.input,
            voice=body.voice,
            language=body.language,
            reference_audio=body.reference_audio or None,
            voice_design=body.voice_design or body.instructions,
        ):
            yield chunk.pcm_s16le

    return StreamingResponse(
        body_stream(),
        media_type="audio/pcm",
        headers={
            "X-HEVI-Audio-Format": "pcm_s16le",
            "X-HEVI-Sample-Rate": "22050",
            "X-HEVI-Engine": body.model,
        },
    )


@openai_router.post("/audio/transcriptions")
async def transcriptions(
    file: Annotated[UploadFile, File(description="本地音频/视频文件")],
    model: Annotated[str, Form()] = "faster_whisper",
    language: Annotated[str | None, Form()] = None,
    response_format: Annotated[str, Form()] = "verbose_json",
    _: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    suffix = Path(file.filename or "audio.bin").suffix or ".bin"
    target = Path(tempfile.gettempdir()) / f"hevi-transcribe-{uuid.uuid4().hex}{suffix}"
    try:
        target.write_bytes(await file.read())
        return transcribe_audio_file(
            source=target,
            language=language,
            response_format=response_format,
            asr_engine=model,
        )
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        target.unlink(missing_ok=True)


@openai_router.websocket("/audio/transcriptions/stream")
async def transcription_stream(websocket: WebSocket) -> None:
    """Proxy a configured streaming ASR sidecar without inventing partial text."""

    await websocket.accept()
    upstream_url = os.getenv("VOICE_ASR_STREAM_WS_URL", "").strip()
    if not upstream_url:
        await websocket.send_json(
            {
                "type": "error",
                "code": "STREAMING_ASR_UNAVAILABLE",
                "message": "VOICE_ASR_STREAM_WS_URL 未配置；当前只有本地批量 ASR。",
            }
        )
        await websocket.close(code=1011)
        return
    try:
        from websockets.asyncio.client import connect

        async with connect(upstream_url) as upstream:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                payload = message.get("bytes") if message.get("bytes") is not None else message.get("text", "")
                if payload is None or not isinstance(payload, (str, bytes)):
                    continue
                await upstream.send(payload)
                response = await upstream.recv()
                if isinstance(response, bytes):
                    await websocket.send_bytes(response)
                else:
                    await websocket.send_text(response)
    except Exception as exc:
        await websocket.send_json({"type": "error", "code": "STREAMING_ASR_FAILED", "message": str(exc)[:300]})
        await websocket.close(code=1011)


__all__ = ["openai_router", "router"]
