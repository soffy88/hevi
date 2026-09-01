"""轻量 Voice Studio API。

这里提供工作台所需的配置与预览能力；真正的音频生成仍通过统一 Task/音频服务执行。
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from obase.persistence import PgPool
from pydantic import BaseModel, Field

from hevi.audio.speech_platform import (
    build_batch_plan,
    get_engine,
    list_voice_profiles,
)
from hevi.audio.speech_platform import (
    diagnostics as speech_diagnostics,
)
from hevi.audio.speech_platform import (
    list_engines as list_speech_engines,
)
from hevi.auth.dependencies import get_current_user
from hevi.credits.account_service import AccountService
from hevi.credits.billing_service import BillingService
from hevi.credits.repository import CreditRepository
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.production.capabilities import CapabilityUnavailableError, require_capability
from hevi.production.contracts import ProductionRequest
from hevi.provider_policy.runtime import probe_provider
from hevi.tasks.repository import TaskRepository
from hevi.tasks.task_service import TaskService

router = APIRouter(prefix="/voice-studio", tags=["voice-studio"])


class EffectsPreviewRequest(BaseModel):
    preset: str
    text: str = "This is a test of the audio effects."


class PersonalityRequest(BaseModel):
    text: str = Field(min_length=1)
    persona: str = Field(min_length=1)


class SynthesisRequest(BaseModel):
    text: str = Field(min_length=1)
    engine: str
    voice: str | None = None
    language: str | None = None
    effects: str | None = None
    reference_audio: str | None = None
    reference_text: str | None = None
    voice_design: str | None = None
    model_config_path: str | None = Field(default=None, alias="model_config")


_EFFECTS = [
    {"name": "radio", "effects": [{"type": "compressor", "params": {"ratio": 4}, "enabled": True}]},
    {
        "name": "deep_voice",
        "effects": [{"type": "pitch", "params": {"semitones": -3}, "enabled": True}],
    },
    {
        "name": "phone_call",
        "effects": [{"type": "bandpass", "params": {"low": 300, "high": 3400}, "enabled": True}],
    },
]
_PERSONAS = [
    {
        "name": "documentary",
        "description": "沉稳纪录片",
        "speaking_style": "清晰、克制",
        "vocabulary": [],
        "emotional_tendency": "客观",
    },
    {
        "name": "energetic",
        "description": "活力解说",
        "speaking_style": "节奏明快",
        "vocabulary": [],
        "emotional_tendency": "积极",
    },
]
_WORKFLOWS = [
    {"id": "clone", "name": "声线克隆", "steps": ["reference", "transcribe", "synthesize", "review"]},
    {"id": "dubbing", "name": "视频译制", "steps": ["asr", "translate", "speaker_map", "synthesize", "mix"]},
    {"id": "long_form", "name": "长篇/有声书", "steps": ["chapterize", "voice_map", "batch", "package"]},
    {"id": "batch", "name": "批量合成", "steps": ["validate", "queue", "synthesize", "manifest"]},
]


async def get_task_service(
    pool: Annotated[PgPool, Depends(get_hevi_pg_pool)],
) -> TaskService:
    repo = TaskRepository(pool)
    billing = BillingService(AccountService(CreditRepository(pool)))
    return TaskService(repo, billing_svc=billing)


@router.get("/effects/presets")
async def list_effects(_: Annotated[dict[str, Any], Depends(get_current_user)]) -> dict[str, Any]:
    return {"presets": _EFFECTS}


@router.post("/effects/preview")
async def preview_effect(
    body: EffectsPreviewRequest, _: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    preset = next(
        (item for item in _EFFECTS if item["name"] == body.preset),
        {"name": body.preset, "effects": []},
    )
    return {
        "preset": preset["name"],
        "effects_count": len(preset["effects"]),
        "effects": preset["effects"],
    }


@router.get("/personality/presets")
async def list_personality(
    _: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    return {"presets": _PERSONAS}


@router.post("/personality/rewrite")
async def rewrite_personality(
    body: PersonalityRequest, _: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    try:
        require_capability("voice_studio_rewrite")
    except CapabilityUnavailableError as exc:
        raise HTTPException(status_code=503, detail=exc.detail()) from exc
    raise AssertionError("voice_studio_rewrite must return or raise")


@router.get("/tts/engines")
async def list_engines(_: Annotated[dict[str, Any], Depends(get_current_user)]) -> dict[str, Any]:
    engines = []
    for item in list_speech_engines():
        if item.kind != "tts":
            continue
        body = item.to_dict()
        body["type"] = "cloud" if item.mode == "network" else "local"
        engines.append(body)
    return {"engines": engines}


@router.get("/catalog")
async def speech_catalog(_: Annotated[dict[str, Any], Depends(get_current_user)]) -> dict[str, Any]:
    """统一返回 TTS、ASR、声线和工作流目录；不加载任何模型。"""
    engines = [item.to_dict() for item in list_speech_engines()]
    return {
        "engines": engines,
        "tts": [item for item in engines if item["kind"] == "tts"],
        "asr": [item for item in engines if item["kind"] == "asr"],
        "voices": [item.to_dict() for item in list_voice_profiles()],
        "workflows": _WORKFLOWS,
        "routing": {"policy": "local-first", "fallback": "explicit-only"},
    }


@router.get("/profiles")
async def speech_profiles(_: Annotated[dict[str, Any], Depends(get_current_user)]) -> dict[str, Any]:
    return {"profiles": [item.to_dict() for item in list_voice_profiles()]}


class BatchPlanRequest(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list, max_length=500)


@router.post("/batch/plan")
async def speech_batch_plan(
    body: BatchPlanRequest,
    _: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    return build_batch_plan(body.items)


@router.get("/diagnostics")
async def speech_diagnostics_endpoint(
    _: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    return speech_diagnostics()


@router.post("/tts/synthesize")
async def synthesize(
    body: SynthesisRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[TaskService, Depends(get_task_service)],
) -> dict[str, Any]:
    await _validate_synthesis_engine(body.engine)
    task = await svc.create_production(
        ProductionRequest(
            source="voice_studio_tts",
            topic=body.text,
            duration_archetype="1-5min",
            video_provider="local",
            audio_provider=body.engine,
            options={
                "text": body.text,
                "engine": body.engine,
                "voice": body.voice,
                "language": body.language or "zh",
                "effects": body.effects,
                "reference_audio": body.reference_audio,
                "reference_text": body.reference_text,
                "voice_design": body.voice_design,
                "model_config": body.model_config_path,
            },
        ),
        user_id=str(user["id"]),
    )
    task = await svc.submit_task(task["id"])
    task_id = str(task["id"])
    return {
        "task_id": task_id,
        "status": task["status"],
        "audio_url": f"/api/tasks/{task_id}/audio",
    }


class TTSCompareRequest(BaseModel):
    engine_a: str
    engine_b: str
    text: str = Field(min_length=1)
    language: str | None = None
    voice_a: str | None = None
    voice_b: str | None = None


async def _validate_synthesis_engine(engine_id: str) -> None:
    if engine_id == "voicebox":
        try:
            require_capability("voice_studio_tts")
        except CapabilityUnavailableError as exc:
            raise HTTPException(status_code=503, detail=exc.detail()) from exc
        status = await probe_provider("voicebox", timeout_s=3.0)
        if not status["ready"]:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "PROVIDER_UNAVAILABLE",
                    "provider": "voicebox",
                    "message": "Voicebox/Gen Engine 当前不可达，未创建音频任务。",
                    "provider_status": status,
                },
            )
        return
    engine = get_engine(engine_id)
    if engine is None:
        raise HTTPException(status_code=422, detail=f"未知语音引擎: {engine_id}")
    if not engine.available:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "SPEECH_ENGINE_UNAVAILABLE",
                "id": engine.id,
                "message": engine.description,
                "setup": engine.setup,
            },
        )


@router.post("/tts/compare")
async def compare_tts(
    body: TTSCompareRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[TaskService, Depends(get_task_service)],
) -> dict[str, Any]:
    """TTS 试听对比：同一段文本在两个引擎/音色下生成，返回两条音频任务。"""
    await _validate_synthesis_engine(body.engine_a)
    await _validate_synthesis_engine(body.engine_b)

    async def create_audio_task(engine: str, voice: str | None) -> dict[str, Any]:
        task = await svc.create_production(
            ProductionRequest(
                source="voice_studio_tts",
                topic=body.text,
                duration_archetype="1-5min",
                video_provider="local",
                audio_provider=engine,
                options={
                    "text": body.text,
                    "voice": voice or "default",
                    "language": body.language or "zh",
                },
            ),
            user_id=str(user["id"]),
        )
        task = await svc.submit_task(task["id"])
        return {
            "task_id": str(task["id"]),
            "status": task["status"],
            "audio_url": f"/api/tasks/{task['id']}/audio",
            "engine": engine,
        }

    task_a, task_b = await asyncio.gather(
        create_audio_task(body.engine_a, body.voice_a),
        create_audio_task(body.engine_b, body.voice_b),
    )

    return {
        "engine_a": task_a,
        "engine_b": task_b,
        "text": body.text,
    }


class ConfigValidateRequest(BaseModel):
    voice_effects: str | None = None
    voice_personas: dict[str, str] | None = None
    tts_engine: str | None = None


@router.post("/config/validate")
async def validate_config(
    body: ConfigValidateRequest,
    _: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    engine_id = body.tts_engine or "voicebox"
    engine = get_engine(engine_id)
    return {
        "valid": bool(engine and engine.available),
        "voice_effects": body.voice_effects,
        "voice_personas_count": len(body.voice_personas or _PERSONAS),
        "tts_engine": engine_id if engine else None,
        "tts_engine_available": bool(engine and engine.available),
    }
