"""Canonical automatic-production boundary.

Content adapters may prepare their own inputs, but execution starts here and
uses the same TaskService lifecycle as the regular task API.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from obase.persistence import PgPool
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.credits.account_service import AccountService
from hevi.credits.billing_service import BillingService, InsufficientCredits
from hevi.credits.repository import CreditRepository
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.production.capabilities import capability_catalog
from hevi.production.contracts import ProductionRequest
from hevi.provider_policy.runtime import inspect_providers
from hevi.tasks.dispatch import schedule_local_compat
from hevi.tasks.repository import TaskRepository
from hevi.tasks.task_service import TaskService

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


class UnifiedGenerateConfig(BaseModel):
    prompt: str = Field(min_length=1)
    duration_archetype: str = "1-5min"
    aspect_ratio: Literal["9:16", "16:9", "1:1"] = "9:16"
    execution_preset: Literal["economy", "balanced", "fast"] = "balanced"
    character_references: list[str] = Field(default_factory=list)
    presenter_id: str | None = None
    emotion_aware_voiceover: bool = False
    locked_shot_list: list[dict[str, Any]] | None = None
    quality_profile: str = "standard"
    options: dict[str, Any] = Field(default_factory=dict)


class UnifiedGenerateRequest(BaseModel):
    source_channel: Literal["hub_quick", "hub_idea2video", "director_console"]
    adapter_type: Literal["default", "explainer", "tongjian", "shortdrama"]
    config: UnifiedGenerateConfig


_ADAPTER_SOURCES = {
    "default": "automatic",
    "explainer": "explainer",
    "tongjian": "tongjian",
    "shortdrama": "shortdrama",
}


def _fuse_generate_options(source_channel: str, cfg: UnifiedGenerateConfig) -> dict[str, Any]:
    """Idea/Novel/Cameo 融合进统一生成 options。失败则原样下发,零回归。"""
    options: dict[str, Any] = {
        **cfg.options,
        "source_channel": source_channel,
        "execution_preset": cfg.execution_preset,
        "emotion_aware_voiceover": cfg.emotion_aware_voiceover,
        "locked_shot_list": cfg.locked_shot_list,
        "character_references": list(cfg.character_references),
    }
    narrative = str(cfg.options.get("narrative_mode") or "")
    novel_text = str(cfg.options.get("novel_text") or "")
    raw_photos = cfg.options.get("cameo_photos") or []
    should_fuse = (
        source_channel == "hub_idea2video"
        or narrative in {"idea", "novel", "script", "cameo"}
        or bool(novel_text)
        or bool(raw_photos)
    )
    if not should_fuse:
        return options
    try:
        from pathlib import Path

        from hevi.script2video.omodul.fuse import fuse_production

        photos = [Path(p) for p in raw_photos if p]
        photos = [p for p in photos if p.exists()]
        explicit = narrative if narrative in {"idea", "novel", "script", "cameo"} else None
        if source_channel == "hub_idea2video" and explicit is None:
            explicit = "idea"
        text = novel_text or cfg.prompt
        fused = fuse_production(
            text,
            requirement=str(cfg.options.get("user_requirement") or ""),
            style=str(cfg.options.get("style_preset") or ""),
            photos=photos or None,
            explicit=explicit,  # type: ignore[arg-type]
        )
        if fused.shot_list.shots:
            options["locked_shot_list"] = fused.locked_shot_payload()
        options["kernel_plan"] = fused.to_dict()
        options["vimax_source"] = fused.source
    except Exception:
        options["kernel_fuse_error"] = True
    return options


@router.get("/capabilities")
async def list_capabilities(
    _: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Return the single truthful availability source for production UIs."""
    capabilities = capability_catalog()
    provider_for_capability = {
        "voice_studio_tts": "voicebox",
        "stock_search": "pexels",
        "longcat_agent": "longcat",
        "streaming_v2v": "joyai",
        "livestream": "duix",
        "mpt": "mpt",
    }
    statuses = await inspect_providers(
        provider_ids=sorted(set(provider_for_capability.values())),
        timeout_s=3.0,
    )
    by_provider = {item["id"]: item for item in statuses}
    for item in capabilities:
        provider_id = provider_for_capability.get(item["id"])
        if provider_id is None:
            continue
        status = by_provider[provider_id]
        item["provider"] = provider_id
        item["provider_configured"] = status["configured"]
        item["provider_reachable"] = status["reachable"]
        item["provider_ready"] = status["ready"]
        item["provider_error"] = status.get("error")
        if not status["ready"] and item["available"]:
            item["readiness"] = "provider_unavailable"
            item["status"] = "provider_unavailable"
            item["production_ready"] = False
            item["message"] = (
                f"{item['name']} 接口已存在，但 Provider 当前不可用；"
                "任务不会提交。"
            )
    return {"capabilities": capabilities}


async def get_pg_pool() -> PgPool:
    return await get_hevi_pg_pool()


async def get_task_service(
    pool: Annotated[PgPool, Depends(get_pg_pool)],
) -> TaskService:
    return TaskService(TaskRepository(pool), BillingService(AccountService(CreditRepository(pool))))


def _serialize(task: dict[str, Any], source: str) -> dict[str, Any]:
    return {
        **task,
        "task_id": str(task.get("id", "")),
        "production_source": source,
        "percent": task.get("progress_pct", 0),
    }


@router.post("/generate", status_code=201)
async def generate_unified(
    body: UnifiedGenerateRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[TaskService, Depends(get_task_service)],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Unified hub/director request boundary for frontend consolidation."""
    source = _ADAPTER_SOURCES[body.adapter_type]
    cfg = body.config
    options = _fuse_generate_options(body.source_channel, cfg)
    options["adapter_type"] = body.adapter_type
    try:
        task = await svc.create_production(
            ProductionRequest(
                source=source,  # type: ignore[arg-type]
                topic=cfg.prompt,
                duration_archetype=cfg.duration_archetype,
                video_provider="auto",
                audio_provider="vibevoice",
                quality_profile=cfg.quality_profile,
                aspect_ratio=cfg.aspect_ratio,
                num_characters=max(1, len(cfg.character_references)),
                subject_ids=cfg.character_references,
                presenter_id=cfg.presenter_id,
                options=options,
            ),
            user_id=str(user["id"]),
        )
        task = await svc.submit_task(task["id"])
    except InsufficientCredits as exc:
        raise HTTPException(
            status_code=402,
            detail={"error": "insufficient_credits", "credits_needed": exc.credits_needed},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if task.get("status") != "queued":
        schedule_local_compat(background_tasks, svc, task["id"])
    return _serialize(task, source)


@router.post("/productions", status_code=201)
async def create_production(
    body: ProductionRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[TaskService, Depends(get_task_service)],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Start one production regardless of which content adapter prepared it."""
    try:
        task = await svc.create_production(body, user_id=str(user["id"]))
        task = await svc.submit_task(task["id"])
    except InsufficientCredits as exc:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "insufficient_credits",
                "credits_needed": exc.credits_needed,
                "credits_available": exc.credits_available,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if task.get("status") != "queued":
        schedule_local_compat(background_tasks, svc, task["id"])
    return _serialize(task, body.source)
