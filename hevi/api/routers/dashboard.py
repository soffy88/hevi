"""v9.1 任务大盘 —— 列表(分页/过滤/状态计数)/详情/成片输出。

数据源:SQLite ``TaskRun``(hevi.core.models),与 ``WorkspaceManager`` 状态中枢
同一张表。``result_video_path`` 只在 completed 时暴露;成片路径优先取
``state_json["result_video_path"]``,否则在工作区沙盒内按 *.mp4 自动发现
(兼容旧管道只落文件不写状态字段的情形)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from hevi.core import workspace as workspace_module
from hevi.core.db import engine
from hevi.core.models import TaskRun

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_ALL_STATUSES = ("pending", "running", "completed", "failed")


def _discover_video(row: TaskRun) -> Path | None:
    """找该工单的成片:先 state_json 显式路径,再按扩展名扫工作区沙盒。"""
    explicit = (row.state_json or {}).get("result_video_path")
    if explicit:
        p = Path(str(explicit))
        if p.is_file():
            return p
    root = Path(workspace_module.DEFAULT_WORKSPACE_ROOT) / row.task_id
    if not root.is_dir():
        return None
    candidates = sorted(root.rglob("*.mp4"), key=lambda p: p.stat().st_size, reverse=True)
    return candidates[0] if candidates else None


def _task_to_dict(row: TaskRun) -> dict[str, Any]:
    d: dict[str, Any] = {
        "task_id": row.task_id,
        "pipeline_type": row.pipeline_type,
        "status": row.status,
        "progress": row.progress,
        "error_log": row.error_log,
        "state_json": dict(row.state_json or {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "result_video_path": None,
    }
    if row.status == "completed":
        video = _discover_video(row)
        if video is not None:
            d["result_video_path"] = str(video)
    return d


def _all_rows() -> list[TaskRun]:
    from sqlmodel import text as _text

    with Session(engine) as session:
        # 按创建先后倒序(SQLite rowid 单调,等价 created_at desc)。
        return list(session.exec(select(TaskRun).order_by(_text("id DESC"))).all())


@router.get("/tasks")
async def list_tasks(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """任务列表:created_at 倒序 + 可选 status 过滤 + 分页;附带全量状态计数。"""
    rows = _all_rows()
    counts = {s: sum(1 for r in rows if r.status == s) for s in _ALL_STATUSES}
    counts["total"] = len(rows)
    if status:
        rows = [r for r in rows if r.status == status]
    page = rows[offset : offset + limit]
    return {
        "total": len(rows),
        "items": [_task_to_dict(r) for r in page],
        "status_counts": counts,
    }


@router.get("/tasks/{task_id}")
async def get_task(task_id: str) -> dict[str, Any]:
    with Session(engine) as session:
        row = session.exec(
            select(TaskRun).where(TaskRun.task_id == task_id)
        ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="task 不存在")
    return _task_to_dict(row)


@router.get("/tasks/{task_id}/output")
async def serve_task_output(task_id: str) -> FileResponse:
    with Session(engine) as session:
        row = session.exec(
            select(TaskRun).where(TaskRun.task_id == task_id)
        ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="task 不存在")
    video = _discover_video(row)
    if video is None or not video.is_file():
        raise HTTPException(status_code=404, detail="成片尚未生成")
    return FileResponse(str(video), media_type="video/mp4", filename=f"{task_id}.mp4")


__all__ = ["router"]
