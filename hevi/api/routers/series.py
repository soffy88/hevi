"""Series API —— 系列资产 + 建集(第 N 集继承)。设计 §3 L2。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from obase.persistence import PgPool
from pydantic import BaseModel

from hevi.auth.dependencies import get_current_user
from hevi.credits.account_service import AccountService
from hevi.credits.billing_service import BillingService
from hevi.credits.repository import CreditRepository
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.series.repository import SeriesRepository
from hevi.series.series_service import SeriesService
from hevi.style.style_service import StylePackRepository, StylePackService
from hevi.tasks.repository import TaskRepository
from hevi.tasks.task_service import TaskService

router = APIRouter(prefix="/series", tags=["series"])


async def get_pg_pool() -> PgPool:
    return await get_hevi_pg_pool()


async def get_series_service(
    pool: Annotated[PgPool, Depends(get_pg_pool)],
) -> SeriesService:
    task_svc = TaskService(
        TaskRepository(pool), BillingService(AccountService(CreditRepository(pool)))
    )
    style_svc = StylePackService(StylePackRepository(pool))
    return SeriesService(SeriesRepository(pool), task_svc, style_svc)


def _check_owner(resource: dict[str, Any], user: dict[str, Any]) -> None:
    if resource.get("user_id") and resource["user_id"] != str(user["id"]):
        raise HTTPException(status_code=404, detail="Series not found")


class SeriesCreateRequest(BaseModel):
    name: str
    subject_ids: list[str] = []
    style_preset: str = ""
    style_pack_id: str | None = None
    spec: dict[str, Any] = {}
    intro_template_id: str | None = None
    outro_template_id: str | None = None


class EpisodeCreateRequest(BaseModel):
    topic: str


@router.post("")
async def create_series(
    body: SeriesCreateRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[SeriesService, Depends(get_series_service)],
) -> dict[str, Any]:
    try:
        return await svc.create_series(
            name=body.name,
            subject_ids=body.subject_ids,
            style_preset=body.style_preset,
            style_pack_id=body.style_pack_id,
            spec=body.spec,
            intro_template_id=body.intro_template_id,
            outro_template_id=body.outro_template_id,
            user_id=str(user["id"]),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("")
async def list_series(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[SeriesService, Depends(get_series_service)],
) -> list[dict[str, Any]]:
    return await svc.list_series(user_id=str(user["id"]))


@router.get("/{series_id}")
async def get_series(
    series_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[SeriesService, Depends(get_series_service)],
) -> dict[str, Any]:
    s = await svc.get_series(series_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Series not found")
    _check_owner(s, user)
    return s


@router.get("/{series_id}/episodes")
async def list_episodes(
    series_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[SeriesService, Depends(get_series_service)],
) -> list[dict[str, Any]]:
    s = await svc.get_series(series_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Series not found")
    _check_owner(s, user)
    return await svc.list_episodes(series_id)


@router.post("/{series_id}/episodes")
async def create_episode(
    series_id: str,
    body: EpisodeCreateRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[SeriesService, Depends(get_series_service)],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """做第 N 集:继承 Series 全部 + 只写新 topic → 建任务并后台执行。"""
    s = await svc.get_series(series_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Series not found")
    _check_owner(s, user)
    try:
        ep = await svc.create_episode(series_id, topic=body.topic)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    # 提交 + 后台跑(与普通任务一致)。
    task = await svc._task_service.submit_task(ep["id"])
    if task.get("status") != "queued":
        background_tasks.add_task(svc._task_service.run_task_background, ep["id"])
    return {**ep, "task_id": str(ep["id"])}
