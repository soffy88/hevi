"""v9.1 基建:任务大盘 API。

``GET /api/dashboard/tasks`` —— 分页 + 状态过滤,按 created_at 倒序返回
TaskRun 列表 + 各状态计数(status_counts),支撑前端「生成任务历史大盘」。
``GET /api/dashboard/tasks/{task_id}/output`` —— 返回工单沙盒内的成片
(主管道 portrait.mp4 / Lite final.mp4 / 先导样片 preview/portrait.mp4)。
查询走 SQLite 索引列(task_id/status/created_at),大盘轮询与 WebSocket 推流并存。
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlmodel import Session, func, select

from hevi.core import workspace as _workspace_module
from hevi.core.db import get_session
from hevi.core.models import TaskRun

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/tasks")
def list_tasks(
    session: SessionDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None, description="按状态过滤,如 completed/failed/running"),
) -> dict[str, object]:
    """返回 {total, status_counts, items:[...]} —— total 供前端算总页数。"""
    query = select(TaskRun)
    count_query = select(func.count()).select_from(TaskRun)
    if status:
        query = query.where(TaskRun.status == status)
        count_query = count_query.where(TaskRun.status == status)
    total = session.exec(count_query).one()
    rows = session.exec(query.order_by(TaskRun.created_at.desc()).offset(offset).limit(limit)).all()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "status_counts": _status_counts(session),
        "items": [_serialize(row) for row in rows],
    }


@router.get("/tasks/{task_id}")
def get_task_run(task_id: str, session: SessionDep) -> dict[str, object]:
    """单工单详情(含颗粒度 state_json,断点续传/排障可读)。"""
    row = session.exec(select(TaskRun).where(TaskRun.task_id == task_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="task 不存在")
    return _serialize(row)


@router.get("/tasks/{task_id}/output")
def get_task_output(task_id: str) -> FileResponse:
    """工单沙盒成片下载/预览(优先全量成片,先导样片次之)。"""
    video = _find_result_video(task_id)
    if video is None:
        raise HTTPException(status_code=404, detail="该任务暂无成片产物")
    return FileResponse(str(video), media_type="video/mp4", filename=video.name)


def _status_counts(session: Session) -> dict[str, int]:
    """各状态任务数:前端顶部统计卡片直接消费,避免客户端只能数当前页。"""
    rows = session.exec(
        select(TaskRun.status, func.count()).group_by(TaskRun.status)
    ).all()
    counts: dict[str, int] = {}
    for status, count in rows:
        counts[str(status)] = int(count)
    return counts


# 成片候选顺序:全量 > 先导样片 > 兜底。目录存在性检查,零 IO 压力。
_RESULT_VIDEO_CANDIDATES = (
    "outputs/final.mp4",
    "portrait.mp4",
    "landscape.mp4",
    "preview/portrait.mp4",
    "preview/landscape.mp4",
    "outputs/portrait.mp4",
)


def _find_result_video(task_id: str) -> Path | None:
    # 运行时读取, 让测试可 monkeypatch hevi.core.workspace.DEFAULT_WORKSPACE_ROOT。
    root = Path(_workspace_module.DEFAULT_WORKSPACE_ROOT) / task_id
    for relative in _RESULT_VIDEO_CANDIDATES:
        candidate = root / relative
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    # 兜底:outputs/ 与根目录下任意 mp4(如 continuous_avatar_*.mp4)。
    for directory in (root / "outputs", root):
        if not directory.is_dir():
            continue
        try:
            for child in directory.iterdir():
                if child.suffix.lower() == ".mp4" and child.stat().st_size > 0:
                    return child
        except OSError:
            continue
    return None


def _serialize(row: TaskRun) -> dict[str, object]:
    return {
        "id": row.id,
        "task_id": row.task_id,
        "pipeline_type": row.pipeline_type,
        "status": row.status,
        "progress": row.progress,
        "error_log": row.error_log,
        "state_json": dict(row.state_json or {}),
        "result_video_path": (
            str(_find_result_video(row.task_id)) if row.status == "completed" else None
        ),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
