"""cinematic_router —— 动画演绎任务路由 (黄金公式出片)。

POST /api/cinematic/animate    提交故事 → 202 受理, 后台跑完整出片
GET  /api/cinematic/tasks/{id} 任务状态/分镜表/产物路径 (与 dashboard 同源 TaskRun)

进度经 ws_manager.broadcast_task_update 推 /api/ws/tasks, 前端实时看
每镜状态 (解说+演绎 镜 i/n)。只做编排边界, 不碰业务规则。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from hevi.cinematic.animation_pipeline import run_animation_pipeline
from hevi.cinematic.golden_formula import GoldenBeat, parse_golden_beats
from hevi.core.db import engine, get_session
from hevi.core.models import TaskRun
from hevi.core.workspace import new_task_id
from hevi.core.ws_manager import connection_manager as _ws_manager
from hevi.explainer.research import _default_llm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cinematic", tags=["cinematic"])


class AnimateRequest(BaseModel):
    """动画演绎出片请求: 故事 + 可选预拆解分镜 + 画幅。"""

    story: str = Field(min_length=8, max_length=3000)
    beats_json: str = Field(default="", description="可选: 预拆解的分镜 JSON 数组(留空走 LLM)")
    ratio: str = Field(default="16:9", pattern="^(16:9|9:16|1:1)$")
    task_id: str = Field(default="", description="留空则服务端生成")


class AnimateAccepted(BaseModel):
    task_id: str
    status: str = "pending"
    progress: int = 0
    n_beats: int = 0


def _utcnow() -> datetime:
    return datetime.now(UTC)


SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/animate", response_model=AnimateAccepted, status_code=202)
async def animate(
    body: AnimateRequest,
    background_tasks: BackgroundTasks,
    session: SessionDep,
) -> AnimateAccepted:
    """提交一个动画演绎任务, 立即 202 + 后台执行。"""
    if not body.task_id:
        body.task_id = new_task_id()
    task_id = body.task_id

    # 预拆解分镜 (前端已编辑) 或留空 → 后台走 LLM
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
        state_json={"story": body.story[:200], "ratio": body.ratio,
                    "n_beats": len(beats) or 0, "stage": "accepted"},
    )
    session.add(row)
    session.commit()

    background_tasks.add_task(_run_animation, task_id, body.story,
                              body.ratio, [b.to_dict() for b in beats])
    return AnimateAccepted(task_id=task_id, status="pending", progress=0,
                           n_beats=len(beats))


async def _run_animation(task_id: str, story: str, ratio: str,
                         beats_dict: list[dict[str, Any]]) -> None:
    """后台出片: 进度写 TaskRun + ws 推送。失败只记状态, 不抛穿。"""

    ws = _ws_manager

    async def _cb(percent: int, stage: str, shot_idx: int) -> None:
        with Session(engine) as session:
            row = session.exec(select(TaskRun).where(TaskRun.task_id == task_id)).first()
            if row is None:
                return
            row.status = "running" if percent < 100 else "completed"
            row.progress = percent
            row.state_json = {**row.state_json, "stage": stage,
                              "shot_index": shot_idx}
            row.updated_at = _utcnow()
            session.add(row)
            session.commit()
        await ws.broadcast_task_update(
            task_id, "running" if percent < 100 else "completed", percent,
            stage=stage, shot_index=shot_idx,
        )

    output_dir = None
    try:
        from hevi.core.workspace import WorkspaceManager

        output_dir = WorkspaceManager(task_id).outputs
        llm = _default_llm()
        beats = [GoldenBeat(**b) for b in beats_dict] or None
        final, beats_out, meta = await run_animation_pipeline(
            story, task_id=task_id, output_dir=output_dir, llm=llm, beats=beats,
            ratio=ratio,
            progress_cb=lambda p, s, i: asyncio.get_event_loop().create_task(
                _cb(p, s, i)
            ),
        )
        # 产物路径记录进 TaskRun (frontend 预览/下载用)
        with Session(engine) as session:
            row = session.exec(select(TaskRun).where(TaskRun.task_id == task_id)).first()
            if row is not None:
                row.state_json = {**row.state_json, "video_path": str(final),
                                  "beats": beats_out, "renderers": meta.get("renderers", [])}
                row.updated_at = _utcnow()
                session.add(row)
                session.commit()
        await ws.broadcast_task_update(task_id, "completed", 100,
                                       stage="完成", video_path=str(final))
    except Exception as exc:
        logger.exception("cinematic %s 出片失败", task_id)
        with Session(engine) as session:
            row = session.exec(select(TaskRun).where(TaskRun.task_id == task_id)).first()
            if row is not None:
                row.status = "failed"
                row.error_log = str(exc)[:4000]
                row.updated_at = _utcnow()
                session.add(row)
                session.commit()
        await ws.broadcast_task_update(task_id, "failed", 0, error=str(exc)[:400])


@router.get("/tasks/{task_id}/video")
def get_animation_video(task_id: str, session: SessionDep) -> Any:
    """产物视频 FileResponse (token 留作生产网关鉴权; 开发直接可看)。"""
    from pathlib import Path as _Path

    from fastapi.responses import FileResponse

    row = session.exec(select(TaskRun).where(TaskRun.task_id == task_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="task 不存在")
    video = _Path(row.state_json.get("video_path") or "")
    if row.status != "completed" or not video.is_file():
        raise HTTPException(status_code=404, detail="视频尚未生成")
    return FileResponse(str(video), media_type="video/mp4",
                        filename=f"{task_id}.mp4")


@router.get("/tasks/{task_id}")
def get_animation_task(task_id: str, session: SessionDep) -> dict[str, object]:
    """任务详情: status/progress/stage/beats/video_path。"""
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


__all__ = ["AnimateAccepted", "AnimateRequest", "router"]

