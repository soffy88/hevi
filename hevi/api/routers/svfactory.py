"""SVFACTORY FastAPI Router.

Endpoints:
- POST /api/batch — submit a batch preset rendering task.
- GET /api/batch/{batch_id} — check batch execution status.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from hevi.svfactory.batch import BatchRunner

router = APIRouter(prefix="/batch", tags=["svfactory-batch"])


class BatchRequest(BaseModel):
    batch_id: str = Field("batch_default", description="批次唯一标识")
    topics: list[str] = Field(["分享", "轮流", "情绪识别"], description="主题列表")
    output_dir: str = Field("output/svfactory", description="输出目录")
    asset_dir: str | None = Field(None, description="分镜素材目录")
    aspect: str = Field("16:9", description="画幅 16:9 或 9:16")
    seed: int = Field(42, description="随机数种子")
    voice: str = Field("zh_CN-huayan-medium.onnx", description="音色")


_ACTIVE_BATCHES: dict[str, dict[str, Any]] = {}


async def _run_bg_batch(runner: BatchRunner) -> None:
    try:
        res = await runner.run()
        _ACTIVE_BATCHES[runner.batch_id] = res
    except Exception as exc:
        _ACTIVE_BATCHES[runner.batch_id] = {"batch_id": runner.batch_id, "error": str(exc), "running": False, "finished": True}


@router.post("")
async def start_batch_production(req: BatchRequest, bg: BackgroundTasks) -> dict[str, Any]:
    """提交批量预设生产任务（串行出片，断点续跑）。"""
    config = req.dict()
    runner = BatchRunner(config)
    _ACTIVE_BATCHES[runner.batch_id] = {"batch_id": runner.batch_id, "running": True, "completed": 0, "total": len(req.topics)}
    bg.add_task(_run_bg_batch, runner)
    return {"status": "started", "batch_id": runner.batch_id, "topics_count": len(req.topics)}


@router.get("/{batch_id}")
async def get_batch_status(batch_id: str) -> dict[str, Any]:
    """查询批次运行状态与每片 manifest 进展。"""
    if batch_id in _ACTIVE_BATCHES:
        return _ACTIVE_BATCHES[batch_id]
    
    # Try reading state file from disk
    state_file = Path(f"output/svfactory/{batch_id}_state.json")
    if state_file.exists():
        try:
            return json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    raise HTTPException(status_code=404, detail=f"Batch not found: {batch_id}")
