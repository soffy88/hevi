"""history_series_router —— 历史现场系列连载 API（P2 自动产线）。

端点:
  GET  /api/history-series/queue      全课节队列+生产状态
  GET  /api/history-series/next       下一个待产课节
  POST /api/history-series/produce     生产指定课（body: lesson_order, 缺省=next）
  POST /api/history-series/produce-daily  每日自动生产（cron 调用, localhost）

产物进 TaskRun(pipeline_type=history_series)，dashboard 与 WS 直接能看到进度。
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from hevi.api.routers.auth import get_current_user
from hevi.history_series.series_producer import (
    TB_ID,
    LessonInfo,
    next_lesson,
    produce_lesson,
    series_queue,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/history-series", tags=["history-series"])


class ProduceRequest(BaseModel):
    lesson_order: int | None = Field(default=None, description="指定课序, 缺省自动取 next")
    tb_id: str = Field(default=TB_ID)
    aspect_ratio: str = Field(default="16:9")
    target_duration_s: int = Field(default=120, ge=60, le=600)


@router.get("/queue")
async def get_queue(tb_id: str = TB_ID) -> list[dict[str, Any]]:
    """全课节连载队列: 每课 production 状态 + task_id。"""
    return await series_queue(tb_id)


@router.get("/next")
async def get_next(tb_id: str = TB_ID) -> dict[str, Any]:
    """下一个待产课节。全册产完返回 {"done": true}。"""
    lesson = await next_lesson(tb_id)
    if lesson is None:
        return {"done": True, "message": "全册已产完"}
    return {"done": False, "lesson_order": lesson.order,
            "title": lesson.title, "ku_count": lesson.ku_count,
            "source_name": lesson.source_name}


@router.post("/produce", status_code=202)
async def produce(
    body: ProduceRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """生产一课: 组装 RunRequest → 提交 tongjian run（后台异步）。"""
    if body.lesson_order is not None:
        lesson = LessonInfo(order=body.lesson_order, title=f"第{body.lesson_order}课")
    else:
        lesson = await next_lesson(body.tb_id)
        if lesson is None:
            raise HTTPException(status_code=409, detail="全册已产完，无待产课节")

    task_id, req = await produce_lesson(
        lesson, tb_id=body.tb_id,
        target_duration_s=body.target_duration_s,
        aspect_ratio=body.aspect_ratio,
    )
    if not req:
        return {"task_id": task_id, "status": "already_completed",
                "lesson_order": lesson.order}

    # 取 raw token（Authorization: Bearer xxx）
    token = (request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
    background_tasks.add_task(
        _submit_tongjian_run, task_id, req, token,
    )
    return {"task_id": task_id, "status": "pending",
            "lesson_order": lesson.order, "lesson_title": lesson.title}


@router.post("/produce-daily", status_code=202)
async def produce_daily(
    background_tasks: BackgroundTasks,
    request: Request,
    tb_id: str = TB_ID,
) -> dict[str, Any]:
    """每日自动生产（供 cron 调用，localhost 免鉴权）。"""
    # 仅 localhost 可调（cron 安全边界）
    client = request.client
    if client and client.host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="仅限 localhost 调用")

    lesson = await next_lesson(tb_id)
    if lesson is None:
        return {"done": True, "message": "全册已产完"}

    task_id, req = await produce_lesson(lesson, tb_id=tb_id)
    if not req:
        return {"task_id": task_id, "status": "already_completed",
                "lesson_order": lesson.order}

    # cron 无 user token → 用 internal env token 或 curl 127.0.0.1 tongjian run
    background_tasks.add_task(
        _submit_tongjian_run_internal, task_id, req,
    )
    return {"task_id": task_id, "status": "pending",
            "lesson_order": lesson.order, "lesson_title": lesson.title}


async def _submit_tongjian_run(task_id: str, req: dict, token: str) -> None:
    """HTTP POST /api/tongjian/run 提交后台出片（async，不阻塞事件循环）。"""

    try:
        import httpx
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8017", timeout=60) as c:
            resp = await c.post(
                "/api/tongjian/run", json=req,
                headers={"Authorization": f"Bearer {token}"},
            )
        result = resp.json()
        logger.info(
            "history_series %s tongjian run submitted: %s", task_id,
            result.get("run_id", resp.status_code),
        )
    except Exception as exc:
        logger.exception("history_series %s tongjian 提交失败: %s", task_id, exc)
        _update_task_status(task_id, "failed", str(exc)[:4000])


async def _submit_tongjian_run_internal(task_id: str, req: dict) -> None:
    """cron 版：无 user token，用注册测试用户登录（async）。"""

    try:
        import httpx
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8017", timeout=30) as c:
            login_resp = await c.post(
                "/api/auth/login",
                json={"email": "p0g0a@hist.works", "password": "p0g0a!2026"},
            )
        token = login_resp.json().get("access_token", "")
    except Exception as exc:
        logger.error("history_series cron 登录失败: %s", exc)
        _update_task_status(task_id, "failed", f"cron 登录失败: {exc}")
        return

    if not token:
        _update_task_status(task_id, "failed", "cron 登录失败: token 空")
        return

    await _submit_tongjian_run(task_id, req, token)


def _update_task_status(task_id: str, status: str, error: str) -> None:
    from sqlmodel import Session, select

    from hevi.core.db import engine
    from hevi.core.models import TaskRun

    with Session(engine) as s:
        row = s.exec(select(TaskRun).where(TaskRun.task_id == task_id)).first()
        if row:
            row.status = status
            row.error_log = error[:4000]
            s.add(row)
            s.commit()


__all__ = ["router"]
