"""Voice Studio API — 声音工作室端点。

提供 VoiceBox 集成的 REST API:
- POST /voice-studio/effects/preview — 预览音频效果
- GET  /voice-studio/effects/presets — 列出效果预设
- POST /voice-studio/personality/rewrite — 人格改写文本
- GET  /voice-studio/personality/presets — 列出人格预设
- GET  /voice-studio/tts/engines — 列出 TTS 引擎
- POST /voice-studio/tts/synthesize — TTS 合成
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from hevi.auth.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice-studio", tags=["voice-studio"])


# ── Effects ──────────────────────────────────────────────────────────────


class EffectsPreviewRequest(BaseModel):
    """效果预览请求。"""
    preset: str  # robotic/radio/echo_chamber/deep_voice/cave/phone_call
    text: str = "This is a test of the audio effects."


@router.get("/effects/presets")
async def list_effects_presets(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """列出可用的音频效果预设。"""
    from hevi.audio.effects import PRESETS
    return {
        "presets": [
            {
                "name": name,
                "effects": [
                    {
                        "type": e.effect_type,
                        "params": e.params,
                        "enabled": e.enabled,
                    }
                    for e in factory().effects
                ],
            }
            for name, factory in PRESETS.items()
        ]
    }


@router.post("/effects/preview")
async def preview_effects(
    body: EffectsPreviewRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """预览音频效果（生成示例音频）。

    注意：此端点返回音频配置信息，实际音频生成需要完整的 TTS 管线。
    """
    from hevi.audio.effects import PRESETS

    factory = PRESETS.get(body.preset)
    if not factory:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown preset: {body.preset}. Available: {list(PRESETS.keys())}",
        )

    chain = factory()
    return {
        "preset": body.preset,
        "text": body.text,
        "effects_count": len(chain.effects),
        "effects": [
            {"type": e.effect_type, "params": e.params}
            for e in chain.effects
        ],
        "message": "Effects preview configured. Use in produce pipeline for actual audio.",
    }


# ── Personality ──────────────────────────────────────────────────────────


class PersonalityRewriteRequest(BaseModel):
    """人格改写请求。"""
    text: str
    persona: str | dict[str, Any]  # 预设名或自定义配置


@router.get("/personality/presets")
async def list_personality_presets(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """列出可用的人格预设。"""
    from hevi.audio.personality import PRESET_PERSONAS
    return {
        "presets": [
            {
                "name": name,
                "description": persona.description,
                "speaking_style": persona.speaking_style,
                "vocabulary": persona.vocabulary,
                "emotional_tendency": persona.emotional_tendency,
            }
            for name, persona in PRESET_PERSONAS.items()
        ]
    }


@router.post("/personality/rewrite")
async def rewrite_with_personality(
    body: PersonalityRewriteRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """用人格改写文本。"""
    from hevi.audio.personality import (
        PersonalityEngine,
        VoicePersona,
        PRESET_PERSONAS,
    )

    engine = PersonalityEngine(llm_fn=None)  # 无 LLM 时用规则改写

    if isinstance(body.persona, str):
        persona = PRESET_PERSONAS.get(body.persona)
        if not persona:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown persona: {body.persona}. Available: {list(PRESET_PERSONAS.keys())}",
            )
    else:
        persona = VoicePersona(
            name=body.persona.get("name", "custom"),
            description=body.persona.get("description", ""),
            speaking_style=body.persona.get("speaking_style", ""),
            vocabulary=body.persona.get("vocabulary", []),
            emotional_tendency=body.persona.get("emotional_tendency", "neutral"),
        )

    result = await engine.rewrite(body.text, persona)
    return {
        "original": result.original_text,
        "rewritten": result.rewritten_text,
        "persona": result.persona_name,
        "model_used": result.model_used,
        "confidence": result.confidence,
    }


# ── TTS Engines ──────────────────────────────────────────────────────────


@router.get("/tts/engines")
async def list_tts_engines(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """列出可用的 TTS 引擎。"""
    from hevi.audio.audio_config import AudioProvider
    from hevi.audio.chatterbox_service import CHATTERBOX_LANGUAGES, TURBO_PARALINGUISTIC_TAGS
    from hevi.audio.kokoro_service import KOKORO_VOICE_CATEGORIES, KOKORO_LANGUAGES

    return {
        "engines": [
            {
                "id": AudioProvider.EDGE_TTS.value,
                "name": "Edge TTS",
                "type": "cloud",
                "description": "Microsoft neural voices, multilingual",
                "requires_gpu": False,
            },
            {
                "id": AudioProvider.VIBEVOICE.value,
                "name": "VibeVoice",
                "type": "local",
                "description": "Multi-speaker local TTS with voice cloning",
                "requires_gpu": True,
            },
            {
                "id": AudioProvider.CHATTERBOX_MULTILINGUAL.value,
                "name": "Chatterbox Multilingual",
                "type": "local",
                "description": "23 languages, zero-shot voice cloning",
                "requires_gpu": True,
                "languages": CHATTERBOX_LANGUAGES,
            },
            {
                "id": AudioProvider.CHATTERBOX_TURBO.value,
                "name": "Chatterbox Turbo",
                "type": "local",
                "description": "English-optimized with paralinguistic tags",
                "requires_gpu": True,
                "paralinguistic_tags": TURBO_PARALINGUISTIC_TAGS,
            },
            {
                "id": AudioProvider.KOKORO.value,
                "name": "Kokoro",
                "type": "local",
                "description": "Lightweight 82M model, CPU real-time, 41 preset voices",
                "requires_gpu": False,
                "languages": KOKORO_LANGUAGES,
                "voice_categories": {
                    k: len(v) for k, v in KOKORO_VOICE_CATEGORIES.items()
                },
            },
            {
                "id": AudioProvider.QWEN_TTS.value,
                "name": "Qwen3-TTS",
                "type": "cloud",
                "description": "Alibaba Cloud expressive Chinese TTS",
                "requires_gpu": False,
            },
        ]
    }


class TTSSynthesizeRequest(BaseModel):
    """TTS 合成请求。"""
    text: str
    engine: str = "edge_tts"
    voice: str | None = None
    language: str = "en"
    effects: str | None = None  # 可选效果预设


@router.post("/tts/synthesize")
async def synthesize_speech(
    body: TTSSynthesizeRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """合成语音。

    注意：此端点返回合成配置信息，实际音频生成需要完整的 TTS 管线。
    在生产中使用 produce pipeline 的 tts_engine 参数。
    """
    from hevi.audio.audio_config import AudioProvider

    engine_id = body.engine
    if engine_id not in [e.value for e in AudioProvider]:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown engine: {engine_id}. Available: {[e.value for e in AudioProvider]}",
        )

    return {
        "engine": engine_id,
        "text": body.text,
        "voice": body.voice,
        "language": body.language,
        "effects": body.effects,
        "message": "TTS synthesis configured. Use in produce pipeline for actual audio generation.",
    }


# ── Integration with Produce Pipeline ────────────────────────────────────


class VoiceConfigRequest(BaseModel):
    """声音配置请求（用于 produce pipeline）。"""
    voice_effects: str | None = None
    voice_personas: dict[str, dict[str, Any]] | None = None
    tts_engine: str | None = None


@router.post("/config/validate")
async def validate_voice_config(
    body: VoiceConfigRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """验证声音配置是否有效。"""
    from hevi.audio.effects import PRESETS as EFFECT_PRESETS
    from hevi.audio.personality import PRESET_PERSONAS
    from hevi.audio.audio_config import AudioProvider

    errors: list[str] = []

    if body.voice_effects and body.voice_effects not in EFFECT_PRESETS:
        errors.append(f"Unknown effects preset: {body.voice_effects}")

    if body.voice_personas:
        for speaker, persona_cfg in body.voice_personas.items():
            if isinstance(persona_cfg, str) and persona_cfg not in PRESET_PERSONAS:
                errors.append(f"Unknown persona for {speaker}: {persona_cfg}")

    if body.tts_engine and body.tts_engine not in [e.value for e in AudioProvider]:
        errors.append(f"Unknown TTS engine: {body.tts_engine}")

    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})

    return {
        "valid": True,
        "voice_effects": body.voice_effects,
        "voice_personas_count": len(body.voice_personas) if body.voice_personas else 0,
        "tts_engine": body.tts_engine,
    }
