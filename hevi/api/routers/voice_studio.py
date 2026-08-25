"""轻量 Voice Studio API。

这里提供工作台所需的配置与预览能力；真正的音频生成仍通过统一 Task/音频服务执行。
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from obase.persistence import PgPool
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.credits.account_service import AccountService
from hevi.credits.billing_service import BillingService
from hevi.credits.repository import CreditRepository
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.production.capabilities import CapabilityUnavailableError, require_capability
from hevi.production.contracts import ProductionRequest
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
_ENGINES = [
    {
        "id": "voicebox",
        "name": "Voicebox",
        "type": "local",
        "description": "可持久化的高质量语音任务（Qwen CustomVoice）",
        "requires_gpu": False,
        "languages": ["zh", "en"],
    }
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
    return {"engines": _ENGINES}


@router.post("/tts/synthesize")
async def synthesize(
    body: SynthesisRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[TaskService, Depends(get_task_service)],
) -> dict[str, Any]:
    try:
        require_capability("voice_studio_tts")
    except CapabilityUnavailableError as exc:
        raise HTTPException(status_code=503, detail=exc.detail()) from exc
    if body.engine != "voicebox":
        raise HTTPException(status_code=422, detail="当前只支持已接入的 voicebox 引擎")
    task = await svc.create_production(
        ProductionRequest(
            source="voice_studio_tts",
            topic=body.text,
            duration_archetype="1-5min",
            video_provider="local",
            audio_provider="voicebox",
            options={
                "text": body.text,
                "voice": body.voice,
                "language": body.language or "zh",
                "effects": body.effects,
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


@router.post("/tts/compare")
async def compare_tts(
    body: TTSCompareRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[TaskService, Depends(get_task_service)],
) -> dict[str, Any]:
    """TTS 试听对比：同一段文本在两个引擎/音色下生成，返回两条音频任务。"""
    try:
        require_capability("voice_studio_tts")
    except CapabilityUnavailableError as exc:
        raise HTTPException(status_code=503, detail=exc.detail()) from exc

    if body.engine_a not in ("voicebox", "vibevoice", "f5_tts", "cosyvoice", "edge_tts") or \
       body.engine_b not in ("voicebox", "vibevoice", "f5_tts", "cosyvoice", "edge_tts"):
        raise HTTPException(status_code=422, detail="当前只支持已接入的引擎")

    async def create_audio_task(engine: str, voice: str | None) -> dict[str, Any]:
        task = await svc.create_production(
            ProductionRequest(
                source="voice_studio_tts_compare",
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


@router.post("/config/validate")
async def validate_config(
    _: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    return {
        "valid": True,
        "voice_effects": None,
        "voice_personas_count": len(_PERSONAS),
        "tts_engine": "vibevoice",
    }
