"""任务大盘 —— canonical PostgreSQL projection in production, SQLite in local mode.

Production reads ``video_tasks`` and its artifact manifest.  The SQLModel
``TaskRun`` projection and workspace scan are retained only for explicit local
mode (and test/debug compatibility); they are never the production source of
truth.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from obase.persistence import PgPool
from sqlmodel import Session, select

from hevi.artifact_store.http import materialize_artifact
from hevi.core import workspace as workspace_module
from hevi.core.config import settings
from hevi.core.db import engine
from hevi.core.models import TaskRun
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.production.artifacts import manifest_from_task
from hevi.tasks.repository import TaskRepository

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_ALL_STATUSES = ("pending", "running", "completed", "failed")


async def _dashboard_pool() -> PgPool | None:
    # Existing dashboard tests intentionally run without Postgres.  Debug is
    # the compatibility switch for that test/local projection; production
    # (debug=false, local_mode=false) fails closed on the canonical database.
    if settings.local_mode or settings.debug:
        return None
    return await get_hevi_pg_pool()


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


def _canonical_task_to_dict(task: dict[str, Any]) -> dict[str, Any]:
    config = task.get("config_json") or {}
    manifest = manifest_from_task(task)
    return {
        "task_id": str(task.get("id", "")),
        "pipeline_type": config.get("production_source") or "task",
        "status": task.get("status"),
        "progress": task.get("progress_pct", 0),
        "error_log": task.get("error"),
        "state_json": config,
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
        "artifact_manifest": manifest.model_dump(mode="json") if manifest else None,
        # Kept as a response-shape compatibility field.  Production readers
        # must use artifact_manifest, never this legacy path projection.
        "result_video_path": None,
    }


async def _canonical_video(task: dict[str, Any]) -> Path:
    manifest = manifest_from_task(task)
    if manifest is None or task.get("status") != "completed":
        raise HTTPException(status_code=404, detail="成片尚未生成")
    return await materialize_artifact(manifest, kind="video")


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
    pool: Annotated[PgPool | None, Depends(_dashboard_pool)] = None,
) -> dict[str, Any]:
    """任务列表:created_at 倒序 + 可选 status 过滤 + 分页;附带全量状态计数。"""
    if isinstance(pool, PgPool):
        tasks = await TaskRepository(pool).list_tasks(limit=200)
        counts = {s: sum(1 for task in tasks if task.get("status") == s) for s in _ALL_STATUSES}
        counts["total"] = len(tasks)
        if status:
            tasks = [task for task in tasks if task.get("status") == status]
        return {
            "total": len(tasks),
            "items": [_canonical_task_to_dict(task) for task in tasks[offset : offset + limit]],
            "status_counts": counts,
        }
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
async def get_task(
    task_id: str,
    pool: Annotated[PgPool | None, Depends(_dashboard_pool)] = None,
) -> dict[str, Any]:
    if isinstance(pool, PgPool):
        import uuid

        try:
            task = await TaskRepository(pool).get_task(uuid.UUID(task_id))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="非法 task_id") from exc
        if task is None:
            raise HTTPException(status_code=404, detail="task 不存在")
        return _canonical_task_to_dict(task)
    with Session(engine) as session:
        row = session.exec(
            select(TaskRun).where(TaskRun.task_id == task_id)
        ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="task 不存在")
    return _task_to_dict(row)


@router.get("/tasks/{task_id}/output")
async def serve_task_output(
    task_id: str,
    pool: Annotated[PgPool | None, Depends(_dashboard_pool)] = None,
) -> FileResponse:
    if isinstance(pool, PgPool):
        import uuid

        try:
            task = await TaskRepository(pool).get_task(uuid.UUID(task_id))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="非法 task_id") from exc
        if task is None:
            raise HTTPException(status_code=404, detail="task 不存在")
        video = await _canonical_video(task)
        return FileResponse(str(video), media_type="video/mp4", filename=f"{task_id}.mp4")
    with Session(engine) as session:
        row = session.exec(
            select(TaskRun).where(TaskRun.task_id == task_id)
        ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="task 不存在")
    legacy_video = _discover_video(row)
    if legacy_video is None or not legacy_video.is_file():
        raise HTTPException(status_code=404, detail="成片尚未生成")
    return FileResponse(str(legacy_video), media_type="video/mp4", filename=f"{task_id}.mp4")


__all__ = ["router"]
