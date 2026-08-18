"""活态制片状态板后端路由 —— 事件流上报/查询 + run 级状态(差距 B7 后端)。

- GET  /api/backlot/runs/{run_id}/events   最近事件(limit)
- POST /api/backlot/runs/{run_id}/events   事件上报(best-effort, 不阻断)
- GET  /api/backlot/runs/{run_id}/status   run 级状态汇总(阶段亮灯/花费/心跳)
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.backlot import (
    EVENT_NOTE,
    BacklotEvent,
    BacklotEventLog,
    backlot_status,
)
from hevi.core.config import settings

router = APIRouter(prefix="/backlot", tags=["backlot"])

# 进程内单例: 按 root keyed, 同一 backlot 目录共享内存尾部缓存
_logs: dict[str, BacklotEventLog] = {}


def _log() -> BacklotEventLog:
    root = Path(settings.backlot_dir)
    key = str(root)
    if key not in _logs:
        _logs[key] = BacklotEventLog(root)
    return _logs[key]


class EmitEventRequest(BaseModel):
    stage: str = ""
    event_type: str = EVENT_NOTE
    payload: dict[str, Any] = Field(default_factory=dict)


@router.get("/runs/{run_id}/events")
async def get_run_events(
    run_id: str,
    limit: int = 100,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """最近事件(内存尾部缓存, 时间序)。limit ∈ [1, 500]。"""
    limit = max(1, min(limit, 500))
    log = _log()
    # 冷启动/跨进程: 内存为空时从 JSONL 回放补齐
    if log.count(run_id) == 0:
        for ev in log.replay_from_disk(run_id):
            log.emit(ev)
    events = log.events(run_id, limit=limit)
    return {"run_id": run_id, "events": [e.to_dict() for e in events], "total": len(events)}


@router.post("/runs/{run_id}/events")
async def emit_run_event(
    run_id: str,
    req: EmitEventRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """上报一条生产事件(best-effort: 失败仅日志, 不阻断调用方)。"""
    ev = BacklotEvent(
        run_id=run_id,
        stage=req.stage,
        event_type=req.event_type,
        payload=req.payload,
    )
    _log().emit(ev)
    return {"ok": True, "event": ev.to_dict()}


@router.get("/runs/{run_id}/status")
async def get_run_status(
    run_id: str,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """run 级状态汇总(阶段亮灯/事件计数/花费估算/最后心跳/失败标志)。"""
    log = _log()
    if log.count(run_id) == 0:
        for ev in log.replay_from_disk(run_id):
            log.emit(ev)
    return backlot_status(log, run_id)
