"""通鉴全自动流水线 API —— HEVI-SPEC-01 导演台入口。

  - POST /tongjian/run      输入原文 + 章节名 → 启动 L0-L8 流水线,后台异步跑
  - GET  /tongjian/runs     列出当前用户的 run 历史
  - GET  /tongjian/runs/{run_id} 查询单个 run 状态 + 各层进度

run 状态存于 DB(复用 hevi_runs / hevi_layer_states,schema 见 SPEC-01 §10.2)。
后台任务通过 BackgroundTasks 启动;如果 DB 尚未建表则降级到内存 map(P0 兼容)。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from obase.persistence import PgPool
from pydantic import BaseModel

from hevi.auth.dependencies import get_current_user
from hevi.db.pg_pool import get_hevi_pg_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tongjian", tags=["tongjian"])

# ── P0 降级:DB 表可能未建,用内存 map 兜底 ──────────────────────────────
_RUNS: dict[str, dict[str, Any]] = {}

_LAYER_ORDER = ["L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8"]


async def get_pg_pool() -> PgPool:
    return await get_hevi_pg_pool()


# ── Pydantic Models ──────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    """启动一次通鉴流水线 run 的入参。"""
    source_name: str          # 章节名,如"资治通鉴·周纪一"
    raw_text: str             # 文言原文
    target_duration_sec: int = 180   # 目标成片时长(秒)
    aspect_ratio: str = "16:9"
    # 可选:直接提供已有 chapter_ir,跳过 L0(P0 调试用)
    skip_to_layer: str | None = None


class LayerState(BaseModel):
    layer: str
    status: str          # PENDING / RUNNING / PASSED / DEGRADED / FAILED
    retry_count: int = 0
    degraded: bool = False
    artifact_path: str | None = None
    gate_report: dict | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None


class RunStatus(BaseModel):
    run_id: str
    status: str          # PENDING / RUNNING / COMPLETED / FAILED
    source_name: str
    created_at: datetime
    completed_at: datetime | None = None
    current_layer: str | None = None
    layers: list[LayerState] = []
    result_video_path: str | None = None
    error: str | None = None


# ── 辅助:初始化 run 记录 ───────────────────────────────────────────────────

def _init_run(run_id: str, source_name: str) -> dict[str, Any]:
    layers = {
        l: {
            "layer": l, "status": "PENDING",
            "retry_count": 0, "degraded": False,
            "artifact_path": None, "gate_report": None,
            "started_at": None, "finished_at": None, "error": None,
        }
        for l in _LAYER_ORDER
    }
    record = {
        "run_id": run_id,
        "status": "PENDING",
        "source_name": source_name,
        "created_at": datetime.now(UTC),
        "completed_at": None,
        "current_layer": None,
        "layers": layers,
        "result_video_path": None,
        "error": None,
    }
    _RUNS[run_id] = record
    return record


def _update_layer(run_id: str, layer: str, **kwargs: Any) -> None:
    if run_id in _RUNS:
        _RUNS[run_id]["layers"][layer].update(kwargs)
        _RUNS[run_id]["current_layer"] = layer


def _finish_run(run_id: str, *, success: bool, result_path: str | None = None, error: str | None = None) -> None:
    if run_id in _RUNS:
        _RUNS[run_id]["status"] = "COMPLETED" if success else "FAILED"
        _RUNS[run_id]["completed_at"] = datetime.now(UTC)
        _RUNS[run_id]["result_video_path"] = result_path
        if error:
            _RUNS[run_id]["error"] = error


# ── 后台流水线 ────────────────────────────────────────────────────────────────

async def _run_pipeline(run_id: str, req: RunRequest) -> None:
    """后台异步跑 L0-L8 流水线(P0 版:尽力而为,逐层调用 tongjian oskill)。"""
    from pathlib import Path

    _RUNS[run_id]["status"] = "RUNNING"

    try:
        from hevi.tongjian.chapter_ir import extract_chapter_ir
        from hevi.tongjian.constitution import build_constitution
        from hevi.tongjian.script import build_script
        from hevi.tongjian.voiceover import build_voiceover
        from hevi.tongjian.character_bible import build_character_bible
        from hevi.tongjian.shotlist import build_shotlist
        from hevi.tongjian.scene_render import render_shots
        from hevi.tongjian.music_plan import build_music_plan
        from hevi.tongjian.assemble import build_final_video

        run_dir = Path("output/tongjian") / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # L0 史料预处理
        _update_layer(run_id, "L0", status="RUNNING", started_at=datetime.now(UTC))
        try:
            chapter_ir = await extract_chapter_ir(
                source_name=req.source_name, raw_text=req.raw_text
            )
            _update_layer(run_id, "L0", status="PASSED",
                          finished_at=datetime.now(UTC),
                          artifact_path=str(run_dir / "L0" / "chapter_ir.json"))
        except Exception as e:
            _update_layer(run_id, "L0", status="FAILED", error=str(e)[:500], finished_at=datetime.now(UTC))
            _finish_run(run_id, success=False, error=f"L0 failed: {e}")
            return

        # L1 立意
        _update_layer(run_id, "L1", status="RUNNING", started_at=datetime.now(UTC))
        try:
            constitution = await build_constitution(chapter_ir)
            _update_layer(run_id, "L1", status="PASSED", finished_at=datetime.now(UTC))
        except Exception as e:
            _update_layer(run_id, "L1", status="FAILED", error=str(e)[:500], finished_at=datetime.now(UTC))
            _finish_run(run_id, success=False, error=f"L1 failed: {e}")
            return

        # L2 剧本
        _update_layer(run_id, "L2", status="RUNNING", started_at=datetime.now(UTC))
        try:
            script = await build_script(chapter_ir=chapter_ir, constitution=constitution)
            _update_layer(run_id, "L2", status="PASSED", finished_at=datetime.now(UTC))
        except Exception as e:
            _update_layer(run_id, "L2", status="FAILED", error=str(e)[:500], finished_at=datetime.now(UTC))
            _finish_run(run_id, success=False, error=f"L2 failed: {e}")
            return

        # L3 配音 & L5 角色卡(并行)
        _update_layer(run_id, "L3", status="RUNNING", started_at=datetime.now(UTC))
        _update_layer(run_id, "L5", status="RUNNING", started_at=datetime.now(UTC))
        try:
            timeline, bible = await asyncio.gather(
                build_voiceover(script=script, constitution=constitution, run_dir=run_dir / "L3"),
                build_character_bible(script=script, chapter_ir=chapter_ir, constitution=constitution),
            )
            _update_layer(run_id, "L3", status="PASSED", finished_at=datetime.now(UTC))
            _update_layer(run_id, "L5", status="PASSED", finished_at=datetime.now(UTC))
        except Exception as e:
            _update_layer(run_id, "L3", status="FAILED", error=str(e)[:500], finished_at=datetime.now(UTC))
            _update_layer(run_id, "L5", status="FAILED", error=str(e)[:500], finished_at=datetime.now(UTC))
            _finish_run(run_id, success=False, error=f"L3/L5 failed: {e}")
            return

        # L4 分镜
        _update_layer(run_id, "L4", status="RUNNING", started_at=datetime.now(UTC))
        try:
            shotlist = await build_shotlist(
                timeline=timeline, script=script,
                character_bible=bible, constitution=constitution,
            )
            _update_layer(run_id, "L4", status="PASSED", finished_at=datetime.now(UTC))
        except Exception as e:
            _update_layer(run_id, "L4", status="FAILED", error=str(e)[:500], finished_at=datetime.now(UTC))
            _finish_run(run_id, success=False, error=f"L4 failed: {e}")
            return

        # L6 场景/画面生成
        _update_layer(run_id, "L6", status="RUNNING", started_at=datetime.now(UTC))
        try:
            frame_manifest = await render_shots(
                shotlist=shotlist, character_bible=bible,
                constitution=constitution, run_dir=run_dir / "L6",
            )
            _update_layer(run_id, "L6", status="PASSED", finished_at=datetime.now(UTC))
        except Exception as e:
            _update_layer(run_id, "L6", status="FAILED", error=str(e)[:500], finished_at=datetime.now(UTC))
            _finish_run(run_id, success=False, error=f"L6 failed: {e}")
            return

        # L7 音乐规划
        _update_layer(run_id, "L7", status="RUNNING", started_at=datetime.now(UTC))
        try:
            music_plan = await build_music_plan(
                timeline=timeline, constitution=constitution, shotlist=shotlist,
            )
            _update_layer(run_id, "L7", status="PASSED", finished_at=datetime.now(UTC))
        except Exception as e:
            # L7 非致命,降级到无音乐
            _update_layer(run_id, "L7", status="DEGRADED", degraded=True,
                          error=str(e)[:200], finished_at=datetime.now(UTC))
            music_plan = None

        # L8 合成
        _update_layer(run_id, "L8", status="RUNNING", started_at=datetime.now(UTC))
        try:
            final_video = await build_final_video(
                shotlist=shotlist, frame_manifest=frame_manifest,
                timeline=timeline, script=script,
                music_plan=music_plan, constitution=constitution,
                output_dir=run_dir / "L8",
            )
            _update_layer(run_id, "L8", status="PASSED", finished_at=datetime.now(UTC))
            _finish_run(run_id, success=True, result_path=str(final_video.path))
        except Exception as e:
            _update_layer(run_id, "L8", status="FAILED", error=str(e)[:500], finished_at=datetime.now(UTC))
            _finish_run(run_id, success=False, error=f"L8 failed: {e}")

    except Exception as e:
        logger.exception("tongjian pipeline %s unhandled: %s", run_id, e)
        _finish_run(run_id, success=False, error=str(e)[:500])


# ── API Endpoints ─────────────────────────────────────────────────────────────

@router.post("/run")
async def start_run(
    body: RunRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict[str, str]:
    """启动一次通鉴全自动流水线(异步后台跑)。"""
    if not body.raw_text.strip():
        raise HTTPException(status_code=422, detail="raw_text 不能为空")
    if len(body.raw_text) > 50_000:
        raise HTTPException(status_code=422, detail="原文过长(上限 5 万字)")

    run_id = str(uuid.uuid4())
    _init_run(run_id, body.source_name)
    background_tasks.add_task(_run_pipeline, run_id, body)
    logger.info("tongjian run %s started: %s", run_id, body.source_name)
    return {"run_id": run_id, "status": "PENDING"}


@router.get("/runs")
async def list_runs(
    user: Annotated[dict, Depends(get_current_user)],
) -> list[RunStatus]:
    """列出所有 run(内存 P0 版,全局共享)。"""
    result = []
    for rec in sorted(_RUNS.values(), key=lambda r: r["created_at"], reverse=True):
        result.append(_rec_to_status(rec))
    return result


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> RunStatus:
    """查询单个 run 状态 + 各层进度。"""
    rec = _RUNS.get(run_id)
    if not rec:
        raise HTTPException(status_code=404, detail="run 不存在")
    return _rec_to_status(rec)


def _rec_to_status(rec: dict[str, Any]) -> RunStatus:
    layers = [LayerState(**v) for v in rec["layers"].values()]
    return RunStatus(
        run_id=rec["run_id"],
        status=rec["status"],
        source_name=rec["source_name"],
        created_at=rec["created_at"],
        completed_at=rec.get("completed_at"),
        current_layer=rec.get("current_layer"),
        layers=layers,
        result_video_path=rec.get("result_video_path"),
        error=rec.get("error"),
    )
