"""cinematic_router —— 动画演绎任务路由 (黄金公式出片)。"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from hevi.cinematic.animation_pipeline import run_animation_pipeline
from hevi.cinematic.golden_formula import GoldenBeat, parse_golden_beats
from hevi.core.db import engine, get_session
from hevi.core.models import TaskRun
from hevi.core.workspace import WorkspaceManager, new_task_id
from hevi.core.ws_manager import connection_manager as ws
from hevi.explainer.research import _default_llm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cinematic", tags=["cinematic"])
SessionDep = Annotated[Session, Depends(get_session)]


class AnimateRequest(BaseModel):
    story: str = Field(min_length=8, max_length=3000)
    beats_json: str = Field(default="")
    ratio: str = Field(default="16:9", pattern="^(16:9|9:16|1:1)$")
    task_id: str = Field(default="")


class AnimateAccepted(BaseModel):
    task_id: str
    status: str = "pending"
    progress: int = 0
    n_beats: int = 0


def _utcnow() -> datetime:
    return datetime.now(UTC)


@router.post("/animate", response_model=AnimateAccepted, status_code=202)
async def animate(
    body: AnimateRequest,
    background_tasks: BackgroundTasks,
    session: SessionDep,
) -> AnimateAccepted:
    if not body.task_id:
        body.task_id = new_task_id()
    task_id = body.task_id
    beats: list[GoldenBeat] = []
    if body.beats_json.strip():
        beats = parse_golden_beats(body.beats_json)
        if not beats:
            raise HTTPException(status_code=422, detail="beats_json 解析失败")
    row = TaskRun(
        task_id=task_id,
        pipeline_type="cinematic_animation",
        status="pending",
        progress=0,
        state_json={
            "story": body.story[:200],
            "ratio": body.ratio,
            "n_beats": len(beats),
            "stage": "accepted",
        },
    )
    session.add(row)
    session.commit()
    background_tasks.add_task(
        _run_animation, task_id, body.story, body.ratio, [b.to_dict() for b in beats]
    )
    return AnimateAccepted(task_id=task_id, n_beats=len(beats))


async def _run_animation(
    task_id: str, story: str, ratio: str, beats_dict: list[dict[str, Any]]
) -> None:
    async def _cb(percent: int, stage: str, shot_idx: int) -> None:
        with Session(engine) as s:
            row = s.exec(select(TaskRun).where(TaskRun.task_id == task_id)).first()
            if row is None:
                return
            row.status = "running" if percent < 100 else "completed"
            row.progress = percent
            row.state_json = {**row.state_json, "stage": stage, "shot_index": shot_idx}
            row.updated_at = _utcnow()
            s.add(row)
            s.commit()
        await ws.broadcast_task_update(
            task_id,
            "running" if percent < 100 else "completed",
            percent,
            stage=stage,
            shot_index=shot_idx,
        )
    try:
        output_dir = WorkspaceManager(task_id).outputs
        llm = _default_llm()
        beats = [GoldenBeat(**b) for b in beats_dict] or None

        def _on_progress(percent: int, stage: str, shot_idx: int) -> None:
            asyncio.get_running_loop().create_task(_cb(percent, stage, shot_idx))

        final, beats_out, _ = await run_animation_pipeline(
            story,
            task_id=task_id,
            output_dir=output_dir,
            llm=llm,
            beats=beats,
            ratio=ratio,
            progress_cb=_on_progress,
        )
        with Session(engine) as s:
            row = s.exec(select(TaskRun).where(TaskRun.task_id == task_id)).first()
            if row is not None:
                row.state_json = {**row.state_json, "video_path": str(final), "beats": beats_out}
                row.updated_at = _utcnow()
                s.add(row)
                s.commit()
        await ws.broadcast_task_update(
            task_id, "completed", 100, stage="完成", video_path=str(final)
        )
    except Exception as exc:
        logger.exception("cinematic %s 出片失败", task_id)
        with Session(engine) as s:
            row = s.exec(select(TaskRun).where(TaskRun.task_id == task_id)).first()
            if row is not None:
                row.status = "failed"
                row.error_log = str(exc)[:4000]
                row.updated_at = _utcnow()
                s.add(row)
                s.commit()
        await ws.broadcast_task_update(task_id, "failed", 0, error=str(exc)[:400])


@router.get("/tasks/{task_id}")
def get_animation_task(task_id: str, session: SessionDep) -> dict[str, object]:
    row = session.exec(select(TaskRun).where(TaskRun.task_id == task_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="task 不存在")
    return {
        "task_id": row.task_id,
        "status": row.status,
        "progress": row.progress,
        "error": row.error_log,
        **row.state_json,
    }


@router.get("/tasks/{task_id}/video")
def get_animation_video(task_id: str, session: SessionDep) -> Any:
    from pathlib import Path as _Path

    row = session.exec(select(TaskRun).where(TaskRun.task_id == task_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="task 不存在")
    video = _Path(row.state_json.get("video_path") or "")
    if row.status != "completed" or not video.is_file():
        raise HTTPException(status_code=404, detail="视频尚未生成")
    return FileResponse(str(video), media_type="video/mp4", filename=f"{task_id}.mp4")


__all__ = ["router"]
