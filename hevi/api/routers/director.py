"""Director API —— L4 导演层入口:自然语言剧情 → 可行性/分镜预览 或 直接产集。设计 §3 L4。

两个端点:
  - POST /director/plan     纯预览:NL → {intent, plan, shot_prompts, graph}(可编辑,不建任务)。
  - POST /director/episodes NL → 可行性门 → 建任务 → 后台出片(run_task 内已含 L3 体检返工闭环)。
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
    """NL → 可行性门 → 建任务 → 后台出片。run_task 内含 L3 体检不合格自动返工。"""
    intent = await parse_intent(body.text)
    merged = {**intent}
    if body.budget_usd is not None:  # 显式预算覆盖 NL 解析出的预算,None 不清空
        merged["budget_usd"] = body.budget_usd
    plan = await produce(**merged)
    if not plan.feasible:
        # 预算不足等 → 止损,不建任务(402 Payment Required)。
        raise HTTPException(status_code=402, detail="; ".join(plan.notes) or "infeasible")

    kwargs: dict[str, Any] = {
        "num_characters": plan.num_characters,
        "style_preset": plan.style,
    }
    if body.auto_rework_rounds is not None:
        kwargs["auto_rework_rounds"] = body.auto_rework_rounds
    try:
        task = await svc.create_task(
            topic=plan.topic,
            duration_archetype=plan.duration_archetype,
            video_provider=plan.video_provider,
            audio_provider=plan.audio_provider,
            user_id=str(user["id"]),
            **kwargs,
        )
    except CostLimitExceeded as e:
        raise HTTPException(status_code=402, detail=str(e)) from e

    sub = await svc.submit_task(task["id"])
    if sub.get("status") != "queued":
        background_tasks.add_task(svc.run_task_background, task["id"])
    return {
        "task_id": str(task["id"]),
        "status": sub.get("status", task.get("status")),
        "intent": intent,
        "plan": asdict(plan),
    }
