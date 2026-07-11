"""自媒体解说短视频通道 API —— hevi.explainer 入口。

  - POST /explainer/run      输入选题 → 启动 E0-E2 流水线,后台异步跑
  - GET  /explainer/runs     列出当前用户的 run 历史
  - GET  /explainer/runs/{run_id} 查询单个 run 状态

P0:内存 map(同 tongjian.py 既有惯例),不建 DB 表。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from hevi.auth.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/explainer", tags=["explainer"])

_RUNS: dict[str, dict[str, Any]] = {}
_LAYER_ORDER = ["E0", "E1", "E2"]  # E0 选题→文案分镜, E1 结构校验, E2 配音+Remotion渲染


class RunRequest(BaseModel):
    topic: str


class LayerState(BaseModel):
    layer: str
    status: str  # PENDING / RUNNING / PASSED / FAILED
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    gate_report: dict | None = None


class RunStatus(BaseModel):
    run_id: str
    status: str  # PENDING / RUNNING / COMPLETED / FAILED
    topic: str
    created_at: datetime
    completed_at: datetime | None = None
    current_layer: str | None = None
    layers: list[LayerState] = []
    result_portrait_path: str | None = None
    result_landscape_path: str | None = None
    error: str | None = None


def _init_run(run_id: str, topic: str) -> dict[str, Any]:
    layers = {
        layer: {
            "layer": layer,
            "status": "PENDING",
            "started_at": None,
            "finished_at": None,
            "error": None,
            "gate_report": None,
        }
        for layer in _LAYER_ORDER
    }
    record = {
        "run_id": run_id,
        "status": "PENDING",
        "topic": topic,
        "created_at": datetime.now(UTC),
        "completed_at": None,
        "current_layer": None,
        "layers": layers,
        "result_portrait_path": None,
        "result_landscape_path": None,
        "error": None,
    }
    _RUNS[run_id] = record
    return record


def _update_layer(run_id: str, layer: str, **kwargs: Any) -> None:
    _RUNS[run_id]["layers"][layer].update(kwargs)
    _RUNS[run_id]["current_layer"] = layer


def _finish_run(
    run_id: str,
    *,
    success: bool,
    portrait_path: str | None = None,
    landscape_path: str | None = None,
    error: str | None = None,
) -> None:
    rec = _RUNS[run_id]
    rec["status"] = "COMPLETED" if success else "FAILED"
    rec["completed_at"] = datetime.now(UTC)
    rec["result_portrait_path"] = portrait_path
    rec["result_landscape_path"] = landscape_path
    if error:
        rec["error"] = error


async def _run_pipeline(run_id: str, topic: str) -> None:
    from hevi.explainer.render import render_storyboard
    from hevi.explainer.storyboard import gate_storyboard, generate_storyboard

    _RUNS[run_id]["status"] = "RUNNING"

    _update_layer(run_id, "E0", status="RUNNING", started_at=datetime.now(UTC))
    try:
        storyboard = await generate_storyboard(topic)
        _update_layer(run_id, "E0", status="PASSED", finished_at=datetime.now(UTC))
    except Exception as e:
        _update_layer(
            run_id, "E0", status="FAILED", error=str(e)[:500], finished_at=datetime.now(UTC)
        )
        _finish_run(run_id, success=False, error=f"E0 failed: {e}")
        return

    _update_layer(run_id, "E1", status="RUNNING", started_at=datetime.now(UTC))
    gate = gate_storyboard(storyboard)
    _update_layer(
        run_id,
        "E1",
        status="PASSED" if gate.passed else "FAILED",
        finished_at=datetime.now(UTC),
        gate_report=gate.model_dump(),
    )
    if not gate.passed:
        _finish_run(run_id, success=False, error=f"E1 gate failed: {gate.errors}")
        return

    _update_layer(run_id, "E2", status="RUNNING", started_at=datetime.now(UTC))
    try:
        run_dir = Path("output/explainer") / run_id
        result = await render_storyboard(storyboard, run_dir)
        _update_layer(run_id, "E2", status="PASSED", finished_at=datetime.now(UTC))
        _finish_run(
            run_id,
            success=True,
            portrait_path=str(result.portrait_path),
            landscape_path=str(result.landscape_path),
        )
    except Exception as e:
        logger.exception("explainer run %s E2 failed", run_id)
        _update_layer(
            run_id, "E2", status="FAILED", error=str(e)[:500], finished_at=datetime.now(UTC)
        )
        _finish_run(run_id, success=False, error=f"E2 failed: {e}")


def _rec_to_status(rec: dict[str, Any]) -> RunStatus:
    return RunStatus(
        run_id=rec["run_id"],
        status=rec["status"],
        topic=rec["topic"],
        created_at=rec["created_at"],
        completed_at=rec.get("completed_at"),
        current_layer=rec.get("current_layer"),
        layers=[LayerState(**v) for v in rec["layers"].values()],
        result_portrait_path=rec.get("result_portrait_path"),
        result_landscape_path=rec.get("result_landscape_path"),
        error=rec.get("error"),
    )


@router.post("/run")
async def start_run(
    body: RunRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict[str, str]:
    if not body.topic.strip():
        raise HTTPException(status_code=422, detail="topic 不能为空")
    if len(body.topic) > 200:
        raise HTTPException(status_code=422, detail="选题过长(上限 200 字)")

    run_id = str(uuid.uuid4())
    _init_run(run_id, body.topic)
    background_tasks.add_task(_run_pipeline, run_id, body.topic)
    logger.info("explainer run %s started: %s", run_id, body.topic)
    return {"run_id": run_id, "status": "PENDING"}


@router.get("/runs")
async def list_runs(user: Annotated[dict, Depends(get_current_user)]) -> list[RunStatus]:
    return [
        _rec_to_status(rec)
        for rec in sorted(_RUNS.values(), key=lambda r: r["created_at"], reverse=True)
    ]


@router.get("/runs/{run_id}")
async def get_run(run_id: str, user: Annotated[dict, Depends(get_current_user)]) -> RunStatus:
    rec = _RUNS.get(run_id)
    if not rec:
        raise HTTPException(status_code=404, detail="run 不存在")
    return _rec_to_status(rec)
