"""活态制片状态板后端路由 —— 事件流 + 分镜联系表审批门 + REPLAY 回放。

- GET  /api/backlot/runs/{run_id}/events         最近事件(limit)
- POST /api/backlot/runs/{run_id}/events         事件上报(best-effort, 不阻断)
- GET  /api/backlot/runs/{run_id}/status         run 级状态汇总(阶段亮灯/花费/心跳)
- POST /api/backlot/runs/{run_id}/shots          登记/更新分镜(自动实测缩略图与质量分)
- GET  /api/backlot/runs/{run_id}/shots          联系表(缩略图/提示词/成本/质量分/状态)
- GET  /api/backlot/runs/{run_id}/contact-sheet  审批板 + 真实 PNG 联络表
- POST /api/backlot/runs/{run_id}/shots/{sid}/decision  approve / reject(写回状态)
- GET  /api/backlot/runs/{run_id}/replay         REPLAY 回放清单(实测时长排布)
- POST /api/backlot/runs/{run_id}/replay/render  真 ffmpeg 拼一条回放 mp4
- GET  /api/backlot/media/{run_id}/{name}        板面媒体(缩略图/联络表/回放片)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.backlot import (
    EVENT_NOTE,
    EVENT_SHOT_DECISION,
    BacklotEvent,
    BacklotEventLog,
    backlot_status,
)
from hevi.backlot.replay import build_replay, render_replay_video
from hevi.backlot.storyboard import StoryboardBoard, StoryboardShot, measure_quality
from hevi.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/backlot", tags=["backlot"])

# 进程内单例: 按 root keyed, 同一 backlot 目录共享内存尾部缓存
_logs: dict[str, BacklotEventLog] = {}


def _log() -> BacklotEventLog:
    root = Path(settings.backlot_dir)
    key = str(root)
    if key not in _logs:
        _logs[key] = BacklotEventLog(root)
    return _logs[key]


def _board(run_id: str) -> StoryboardBoard:
    return StoryboardBoard(settings.backlot_dir, run_id)


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


# ---------------------------------------------------------------------------
# 分镜联系表审批门
# ---------------------------------------------------------------------------


class ShotRequest(BaseModel):
    scene_id: str
    index: int = 0
    title: str = ""
    prompt: str = ""
    source_path: str = ""
    duration_s: float = 0.0
    cost_usd: float = 0.0
    #: 调用方自报的质量分。只作对照记录, 不参与审批判定(审批看实测分)。
    declared_score: float | None = None
    measure: bool = True


class ShotDecisionRequest(BaseModel):
    decision: str
    reason: str = ""
    reviewer: str = "anonymous"


@router.post("/runs/{run_id}/shots")
async def upsert_shot(
    run_id: str,
    req: ShotRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """登记/更新一格分镜。给了 source_path 就自己抽代表帧、实测质量分。"""
    board = _board(run_id)
    quality: dict[str, Any] = {}
    thumbnail = ""
    if req.measure and req.source_path:
        try:
            quality = measure_quality(
                req.source_path, work_dir=board.dir / "quality" / req.scene_id
            )
            thumbnail = str(quality.get("thumbnail") or "")
        except Exception as exc:
            logger.warning("backlot quality measure failed (%s/%s): %s", run_id, req.scene_id, exc)
            quality = {"error": str(exc), "unmeasured": ["exposure", "contrast", "motion"]}
    shot = StoryboardShot(
        scene_id=req.scene_id,
        index=req.index,
        title=req.title,
        prompt=req.prompt,
        thumbnail=thumbnail,
        source_path=req.source_path,
        duration_s=req.duration_s,
        cost_usd=req.cost_usd,
        quality=quality,
        declared_score=req.declared_score,
    )
    saved = board.upsert(shot)
    return {"ok": True, "shot": saved.to_dict(), "summary": board.summary()}


@router.get("/runs/{run_id}/shots")
async def list_shots(
    run_id: str,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """联系表数据: 每格的缩略图 / 提示词 / 成本 / 质量分 / 审批状态。"""
    board = _board(run_id)
    return {
        "run_id": run_id,
        "shots": [s.to_dict() for s in board.shots()],
        "summary": board.summary(),
    }


@router.get("/runs/{run_id}/contact-sheet")
async def get_contact_sheet(
    run_id: str,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """审批板: 联系表 PNG + 逐格决策 + 汇总(未批完则 gate=blocked)。"""
    return _board(run_id).contact_sheet()


@router.post("/runs/{run_id}/shots/{scene_id}/decision")
async def decide_shot(
    run_id: str,
    scene_id: str,
    req: ShotDecisionRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """approve / reject 写回状态, 并落一条不可变的 shot_decision 事件。"""
    board = _board(run_id)
    try:
        shot = board.decide(
            scene_id,
            decision=req.decision,
            reason=req.reason,
            reviewer=req.reviewer,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _log().emit(
        BacklotEvent(
            run_id=run_id,
            stage="storyboard",
            event_type=EVENT_SHOT_DECISION,
            payload={"scene_id": scene_id, "decision": req.decision, "reason": req.reason},
        )
    )
    return {"ok": True, "shot": shot.to_dict(), "summary": board.summary()}


# ---------------------------------------------------------------------------
# REPLAY 回放
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/replay")
async def get_replay(
    run_id: str,
    include: str = "approved",
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """回放清单: 每段时长都由 ffprobe 实测, 没媒体的段落显式记 unmeasured。"""
    board = _board(run_id)
    log = _log()
    if log.count(run_id) == 0:
        for ev in log.replay_from_disk(run_id):
            log.emit(ev)
    return build_replay(
        board,
        events=[e.to_dict() for e in log.events(run_id, limit=200)],
        include=include,
    )


@router.post("/runs/{run_id}/replay/render")
async def render_replay(
    run_id: str,
    include: str = "approved",
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """真 ffmpeg 拼接回放片; 不可渲染时如实返回 ok=False 而不是给占位视频。"""
    board = _board(run_id)
    replay = build_replay(board, include=include)
    out = board.dir / f"replay_{include}.mp4"
    result = render_replay_video(replay, out)
    return {"ok": True, "replay": replay, "render": result}


@router.get("/media/{run_id}/{name}")
async def get_board_media(
    run_id: str,
    name: str,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> FileResponse:
    """板面媒体(缩略图/联络表/回放片)。路径锁死在 backlot 目录内。"""
    root = Path(settings.backlot_dir).resolve()
    if any(ch in name for ch in ("/", "\\", "..")) or any(ch in run_id for ch in ("/", "\\", "..")):
        raise HTTPException(status_code=400, detail="invalid media name")
    path = (root / run_id / name).resolve()
    if not str(path).startswith(str(root) + "/") or not path.is_file():
        raise HTTPException(status_code=404, detail=f"not found: {name}")
    return FileResponse(path)
