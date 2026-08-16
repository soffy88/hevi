"""history_series_router —— 历史现场系列连载 API (P2 自动产线)。"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.core.ws_manager import connection_manager as ws
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
    lesson_order: int | None = None
    tb_id: str = TB_ID
    aspect_ratio: str = "16:9"
    target_duration_s: int = Field(default=120, ge=60, le=600)


@router.get("/queue")
async def get_queue(tb_id: str = TB_ID) -> list[dict[str, Any]]:
    return await series_queue(tb_id)


@router.get("/next")
async def get_next(tb_id: str = TB_ID) -> dict[str, Any]:
    lesson = await next_lesson(tb_id)
    if lesson is None:
        return {"done": True, "message": "全册已产完"}
    return {
        "done": False,
        "lesson_order": lesson.order,
        "title": lesson.title,
        "ku_count": lesson.ku_count,
        "source_name": lesson.source_name,
    }


@router.post("/produce", status_code=202)
async def produce(
    body: ProduceRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    lesson: LessonInfo
    if body.lesson_order is not None:
        lesson = LessonInfo(order=body.lesson_order, title=f"第{body.lesson_order}课")
    else:
        candidate = await next_lesson(body.tb_id)
        if candidate is None:
            raise HTTPException(status_code=409, detail="全册已产完")
        lesson = candidate
    task_id, req = await produce_lesson(
        lesson,
        tb_id=body.tb_id,
        target_duration_s=body.target_duration_s,
        aspect_ratio=body.aspect_ratio,
    )
    if not req:
        return {
            "task_id": task_id,
            "status": "already_completed",
            "lesson_order": lesson.order,
        }
    token = (request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
    background_tasks.add_task(_submit, task_id, req, token)
    return {
        "task_id": task_id,
        "status": "pending",
        "lesson_order": lesson.order,
        "lesson_title": lesson.title,
    }


@router.post("/produce-daily", status_code=202)
async def produce_daily(
    background_tasks: BackgroundTasks,
    request: Request,
    tb_id: str = TB_ID,
) -> dict[str, Any]:
    client = request.client
    if client and client.host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="仅限 localhost")
    lesson = await next_lesson(tb_id)
    if lesson is None:
        return {"done": True, "message": "全册已产完"}
    task_id, req = await produce_lesson(lesson, tb_id=tb_id)
    if not req:
        return {
            "task_id": task_id,
            "status": "already_completed",
            "lesson_order": lesson.order,
        }
    background_tasks.add_task(_submit_cron, task_id, req)
    return {
        "task_id": task_id,
        "status": "pending",
        "lesson_order": lesson.order,
        "lesson_title": lesson.title,
    }


async def _submit(task_id: str, req: dict[str, Any], token: str) -> None:
    import httpx

    try:
        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:8017", timeout=60
        ) as c:
            resp = await c.post(
                "/api/tongjian/run",
                json=req,
                headers={"Authorization": f"Bearer {token}"},
            )
        logger.info(
            "history_series %s tongjian submitted: %s",
            task_id,
            resp.json().get("run_id"),
        )
    except Exception as e:
        logger.exception("history_series %s 提交失败: %s", task_id, e)
        _fail(task_id, str(e)[:4000])


async def _submit_cron(task_id: str, req: dict[str, Any]) -> None:
    import httpx

    try:
        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:8017", timeout=30
        ) as c:
            lr = await c.post(
                "/api/auth/login",
                json={"email": "p0g0a@hist.works", "password": "p0g0a!2026"},
            )
        token = lr.json().get("access_token", "")
        if not token:
            _fail(task_id, "cron 登录失败")
            return
        await _submit(task_id, req, token)
    except Exception as e:
        _fail(task_id, str(e)[:4000])


def _fail(task_id: str, error: str) -> None:
    from sqlmodel import Session, select

    from hevi.core.db import engine
    from hevi.core.models import TaskRun

    with Session(engine) as s:
        row = s.exec(select(TaskRun).where(TaskRun.task_id == task_id)).first()
        if row:
            row.status = "failed"
            row.error_log = error[:4000]
            s.add(row)
            s.commit()


@router.post("/animate", status_code=202)
async def animate_episode(
    body: ProduceRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """动画管道出片（零 API 额度, HTML/CSS 动画 + TTS, 替代 tongjian SDXL 渲染）。"""
    lesson: LessonInfo
    if body.lesson_order is not None:
        lesson = LessonInfo(order=body.lesson_order, title=f"第{body.lesson_order}课")
    else:
        candidate = await next_lesson(body.tb_id)
        if candidate is None:
            raise HTTPException(status_code=409, detail="全册已产完")
        lesson = candidate
    task_id, req = await produce_lesson(
        lesson,
        tb_id=body.tb_id,
        target_duration_s=body.target_duration_s,
        aspect_ratio=body.aspect_ratio,
    )
    if not req:
        return {
            "task_id": task_id,
            "status": "already_completed",
            "lesson_order": lesson.order,
        }
    background_tasks.add_task(_run_animation_episode, task_id, req, lesson)
    return {
        "task_id": task_id,
        "status": "pending",
        "lesson_order": lesson.order,
        "lesson_title": lesson.title,
    }


async def _run_animation_episode(
    task_id: str, req: dict[str, Any], lesson: LessonInfo
) -> None:
    """后台动画出片, 进度写 TaskRun + WS 推送。"""
    from hevi.history_series.series_animator import animate_lesson

    textbook = req.get("raw_text", "").replace("（教材主述）", "")

    async def _cb(percent: int, stage: str) -> None:
        from sqlmodel import Session, select

        from hevi.core.db import engine as _eng
        from hevi.core.models import TaskRun

        with Session(_eng) as s:
            row = s.exec(select(TaskRun).where(TaskRun.task_id == task_id)).first()
            if row is None:
                return
            row.status = "running" if percent < 100 else "completed"
            row.progress = percent
            row.state_json = {**row.state_json, "stage": stage}
            s.add(row)
            s.commit()
        await ws.broadcast_task_update(
            task_id,
            "running" if percent < 100 else "completed",
            percent,
            stage=stage,
        )

    try:
        await _cb(10, "LLM 拆解分镜")
        final, beats = await animate_lesson(
            textbook,
            lesson_title=lesson.title,
            output_dir=Path(f"data/workspace/{task_id}/outputs"),
        )
        await _cb(100, "完成")
        from sqlmodel import Session, select

        from hevi.core.db import engine as _eng
        from hevi.core.models import TaskRun

        with Session(_eng) as s:
            row = s.exec(select(TaskRun).where(TaskRun.task_id == task_id)).first()
            if row is not None:
                row.status = "completed"
                row.progress = 100
                row.state_json = {
                    **row.state_json,
                    "video_path": str(final),
                    "beats": beats,
                    "stage": "完成",
                }
                s.add(row)
                s.commit()
        await ws.broadcast_task_update(
            task_id, "completed", 100, stage="完成", video_path=str(final)
        )
    except Exception as exc:
        logger.exception("animation episode %s 失败", task_id)
        _fail(task_id, str(exc)[:4000])
