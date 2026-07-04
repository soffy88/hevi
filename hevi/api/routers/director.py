"""Director API —— L4 导演层入口:自然语言 + 结构化片表单 → 可行性预览 / 直接产集。设计 §3 L4。

  - POST /director/plan     NL → {intent, plan, shot_prompts, graph}(预览,不建任务)。
  - POST /director/episodes NL + 8 层片表单 → 可行性门 → 建任务 → 后台出片(含 L3 体检返工)。

结构化字段(画幅/风格/画质/角色/provider…)全部透传进 config_json,逐字段驱动 orchestrate。
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from obase.persistence import PgPool
from pydantic import BaseModel

from hevi.auth.dependencies import get_current_user
from hevi.cost.circuit_breaker import CostLimitExceeded
from hevi.credits.account_service import AccountService
from hevi.credits.billing_service import BillingService
from hevi.credits.repository import CreditRepository
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.director.intent import parse_intent
from hevi.director.planner import plan_from_text
from hevi.director.producer import produce
from hevi.tasks.repository import TaskRepository
from hevi.tasks.task_service import TaskService
from hevi.video.presets import EXECUTION_PRESETS

router = APIRouter(prefix="/director", tags=["director"])


async def get_pg_pool() -> PgPool:
    return await get_hevi_pg_pool()


async def get_task_service(
    pool: Annotated[PgPool, Depends(get_pg_pool)],
) -> TaskService:
    return TaskService(TaskRepository(pool), BillingService(AccountService(CreditRepository(pool))))


class PlanRequest(BaseModel):
    text: str
    num_shots: int = 4
    character_reference: str | None = None


class EpisodeRequest(BaseModel):
    text: str
    # ① 立意
    duration_archetype: str | None = None  # 覆盖 LLM 猜的时长档
    aspect_ratio: str = "9:16"  # 9:16 竖 / 16:9 横 / 1:1 方
    # ② 角色
    subject_id: str | None = None  # 绑主体 → i2v 跨镜一致
    avatar_portrait: str | None = None  # 数字人肖像
    num_characters: int | None = None
    # ④ 视觉风格
    style_preset: str | None = None  # 20 预设之一
    prompt_style: str | None = None
    prompt_lighting: str | None = None
    prompt_camera: str | None = None
    prompt_color_grade: str | None = None
    # ⑤ 分镜
    transition: str = "fade"
    per_shot_routing: bool = False
    # ⑥ 音频
    language: str = "zh"
    audio_provider: str | None = None
    # ⑦ 成片规格
    quality_profile: str = "standard"
    # ⑧ 生产
    preset: str | None = None  # economy/balanced/fast(provider/quality 底,显式字段覆盖)
    video_provider: str | None = None  # None → auto 成本路由
    budget_usd: float | None = None
    auto_rework_rounds: int | None = None


@router.post("/plan")
async def director_plan(
    body: PlanRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """预览:剧情文本 → 意图 + 可行性 plan + 分镜 prompts + 可执行 canvas 图(不建任务)。"""
    result = await plan_from_text(
        text=body.text,
        num_shots=body.num_shots,
        character_reference=body.character_reference,
    )
    return {**result, "plan": asdict(result["plan"])}


@router.post("/episodes")
async def director_create_episode(
    body: EpisodeRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[TaskService, Depends(get_task_service)],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """NL + 片表单 → 可行性门 → 建任务 → 后台出片。结构化字段逐条驱动 orchestrate。"""
    intent = await parse_intent(body.text)

    # 结构化字段优先于 LLM 猜的值。
    duration = body.duration_archetype or intent.get("duration_archetype", "1-5min")
    num_chars = (
        body.num_characters if body.num_characters is not None else intent.get("num_characters", 1)
    )

    # 执行预设作 provider/quality 的底,显式字段覆盖。
    base_video, base_audio, base_quality = "auto", "vibevoice", body.quality_profile
    if body.preset and body.preset in EXECUTION_PRESETS:
        p = EXECUTION_PRESETS[body.preset]
        base_video, base_audio, base_quality = p.video_provider, p.audio_provider, p.quality_profile
    video_provider = body.video_provider or base_video
    audio_provider = body.audio_provider or base_audio
    quality_profile = body.quality_profile if body.quality_profile != "standard" else base_quality

    mode = "i2v" if body.subject_id else "t2v"  # 绑了角色 → i2v 锁定
    try:
        plan = await produce(
            topic=intent["topic"],
            duration_archetype=duration,
            audio_provider=audio_provider,
            video_provider=video_provider,
            style=body.style_preset or intent.get("style", "cinematic"),
            num_characters=num_chars,
            budget_usd=body.budget_usd,
            mode=mode,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not plan.feasible:
        raise HTTPException(status_code=402, detail="; ".join(plan.notes) or "infeasible")

    # 结构化字段 → config_json → run_task 逐条透传进 orchestrate。
    kwargs: dict[str, Any] = {
        "num_characters": num_chars,
        "aspect_ratio": body.aspect_ratio,
        "quality_profile": quality_profile,
        "transition": body.transition,
        "per_shot_routing": body.per_shot_routing,
        "language": body.language,
    }
    for k, v in (
        ("style_preset", body.style_preset),
        ("prompt_style", body.prompt_style),
        ("prompt_lighting", body.prompt_lighting),
        ("prompt_camera", body.prompt_camera),
        ("prompt_color_grade", body.prompt_color_grade),
        ("avatar_portrait", body.avatar_portrait),
        ("subject_id", body.subject_id),
    ):
        if v:
            kwargs[k] = v
    if body.auto_rework_rounds is not None:
        kwargs["auto_rework_rounds"] = body.auto_rework_rounds

    try:
        task = await svc.create_task(
            topic=plan.topic,
            duration_archetype=duration,
            video_provider=plan.video_provider,
            audio_provider=audio_provider,
            user_id=str(user["id"]),
            **kwargs,
        )
    except CostLimitExceeded as e:
        raise HTTPException(status_code=402, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    sub = await svc.submit_task(task["id"])
    if sub.get("status") != "queued":
        background_tasks.add_task(svc.run_task_background, task["id"])
    return {
        "task_id": str(task["id"]),
        "status": sub.get("status", task.get("status")),
        "intent": intent,
        "plan": asdict(plan),
        "spec": {
            "duration_archetype": duration,
            "aspect_ratio": body.aspect_ratio,
            "quality_profile": quality_profile,
            "video_provider": plan.video_provider,
            "audio_provider": audio_provider,
            "num_characters": num_chars,
            "subject_locked": bool(body.subject_id),
            "avatar": bool(body.avatar_portrait),
        },
    }
