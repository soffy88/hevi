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
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from obase.persistence import PgPool
from pydantic import BaseModel, Field

from hevi.tongjian.schemas import Constitution, LayerConfig, Script

from hevi.auth.dependencies import get_current_user
from hevi.auth.jwt_handler import decode_access_token
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

    source_name: str  # 章节名,如"资治通鉴·周纪一"
    raw_text: str  # 文言原文
    target_duration_sec: int = 180  # 目标成片时长(秒)
    aspect_ratio: str = "16:9"
    # 可选:直接提供已有 chapter_ir,跳过 L0(P0 调试用)
    skip_to_layer: str | None = None
    # 人工审核卡点:="L2" 时跑完 L0-L2 出剧本就暂停(status=AWAITING_REVIEW),等人工
    # 审核/编辑剧本后再 /resume 续跑 L3-L8。None=一口气跑完不暂停。
    pause_after: str | None = None
    # 每层的模型选择 + 可调参数(键 "L0".."L8"),前端逐层调参。缺省=各层默认。
    layer_config: dict[str, LayerConfig] = Field(default_factory=dict)


class ScriptReviewUpdate(BaseModel):
    """人工审核提交:编辑后的剧本(必填)+ 可选改过的立意。"""

    script: Script
    constitution: Constitution | None = None


class LayerState(BaseModel):
    layer: str
    status: str  # PENDING / RUNNING / PASSED / DEGRADED / FAILED
    retry_count: int = 0
    degraded: bool = False
    artifact_path: str | None = None
    gate_report: dict | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None


class RunStatus(BaseModel):
    run_id: str
    status: str  # PENDING / RUNNING / COMPLETED / FAILED
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
            "layer": l,
            "status": "PENDING",
            "retry_count": 0,
            "degraded": False,
            "artifact_path": None,
            "gate_report": None,
            "started_at": None,
            "finished_at": None,
            "error": None,
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


def _finish_run(
    run_id: str, *, success: bool, result_path: str | None = None, error: str | None = None
) -> None:
    if run_id in _RUNS:
        _RUNS[run_id]["status"] = "COMPLETED" if success else "FAILED"
        _RUNS[run_id]["completed_at"] = datetime.now(UTC)
        _RUNS[run_id]["result_video_path"] = result_path
        if error:
            _RUNS[run_id]["error"] = error


# ── 后台流水线 ────────────────────────────────────────────────────────────────


def _apply_cloud_avatar_preset(req: RunRequest) -> None:
    """固化「云水墨数字人」preset:选了 L6=cloud_avatar,就自动给整条链配齐验证过的云配置
    (2026-07-10 端到端跑通那套:L0-L2/L4/L5 云 qwen 出剧本、L3 edge_tts 配音,绕开欠费的
    公共 DashScope + 死掉的本地 GPU)。只补「模型未指定」的层——即便某层已带 params(如
    L1.n / L2.dramatize)也要把 model 填上,否则该层会回退到坏掉的 default 本地模型。
    """
    _l6 = req.layer_config.get("L6")
    if not (_l6 and _l6.model == "cloud_avatar"):
        return
    for _lyr, _m in {
        "L0": "qwen_cloud",
        "L1": "qwen_cloud",
        "L2": "qwen_cloud",
        "L4": "qwen_cloud",
        "L5": "qwen_cloud",
        "L3": "edge_tts",
    }.items():
        _cur = req.layer_config.get(_lyr)
        if _cur is None:
            req.layer_config[_lyr] = LayerConfig(model=_m)
        elif not _cur.model:
            req.layer_config[_lyr] = _cur.model_copy(update={"model": _m})


def _pipeline_helpers(run_id: str, req: RunRequest):
    """构造逐层 provider/参数/门禁助手(L0-L2 与 L3-L8 两段共用)。"""
    from obase.provider_registry import ProviderRegistry

    def _llm(layer: str):
        cfg = req.layer_config.get(layer)
        return ProviderRegistry.get().llm(cfg.model if cfg and cfg.model else "default")

    def _tts(layer: str):
        cfg = req.layer_config.get(layer)
        if not (cfg and cfg.model):
            return None  # 用该层默认 TTS
        return ProviderRegistry.get().generic("audio", cfg.model)

    def _params(layer: str) -> dict:
        cfg = req.layer_config.get(layer)
        return dict(cfg.params) if cfg and cfg.params else {}

    def _gate_done(layer: str, gate) -> None:
        """门禁非阻塞:不过标只标 DEGRADED + 记 gate_report,不中断流水线(通鉴"永不卡死")。"""
        _update_layer(
            run_id,
            layer,
            status="PASSED" if gate.passed else "DEGRADED",
            degraded=not gate.passed,
            gate_report=gate.model_dump(),
            finished_at=datetime.now(UTC),
        )

    return _llm, _tts, _params, _gate_done


def _persist_review(run_dir, constitution, script) -> None:
    """把立意+剧本落盘(L2/review.json),审核/续跑读得到,API 重启也不丢草稿。"""
    import json
    from pathlib import Path

    d = Path(run_dir) / "L2"
    d.mkdir(parents=True, exist_ok=True)
    (d / "review.json").write_text(
        json.dumps(
            {"constitution": constitution.model_dump(), "script": script.model_dump()},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


async def _run_pipeline(run_id: str, req: RunRequest) -> None:
    """后台异步跑 L0-L2(出剧本)。pause_after=="L2" 则停在审核态等人工;否则直接续渲染。"""
    from pathlib import Path

    _RUNS[run_id]["status"] = "RUNNING"

    try:
        from hevi.tongjian.chapter_ir import extract_chapter_ir
        from hevi.tongjian.constitution import build_constitution
        from hevi.tongjian.script import build_script

        run_dir = Path("output/tongjian") / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        _apply_cloud_avatar_preset(req)
        _llm, _tts, _params, _gate_done = _pipeline_helpers(run_id, req)

        # L0 史料预处理
        _update_layer(run_id, "L0", status="RUNNING", started_at=datetime.now(UTC))
        try:
            chapter_ir = await extract_chapter_ir(
                source_name=req.source_name, raw_text=req.raw_text, llm=_llm("L0")
            )
            _update_layer(
                run_id,
                "L0",
                status="PASSED",
                finished_at=datetime.now(UTC),
                artifact_path=str(run_dir / "L0" / "chapter_ir.json"),
            )
        except Exception as e:
            _update_layer(
                run_id, "L0", status="FAILED", error=str(e)[:500], finished_at=datetime.now(UTC)
            )
            _finish_run(run_id, success=False, error=f"L0 failed: {e}")
            return

        # L1 立意
        _update_layer(run_id, "L1", status="RUNNING", started_at=datetime.now(UTC))
        try:
            constitution, g1 = await build_constitution(
                chapter_ir, llm=_llm("L1"), n=int(_params("L1").get("n", 3))
            )
            _gate_done("L1", g1)
        except Exception as e:
            _update_layer(
                run_id, "L1", status="FAILED", error=str(e)[:500], finished_at=datetime.now(UTC)
            )
            _finish_run(run_id, success=False, error=f"L1 failed: {e}")
            return

        # L2 剧本
        _update_layer(run_id, "L2", status="RUNNING", started_at=datetime.now(UTC))
        try:
            script, g2 = await build_script(
                chapter_ir=chapter_ir,
                constitution=constitution,
                llm=_llm("L2"),
                dramatize=bool(_params("L2").get("dramatize", True)),
            )
            _gate_done("L2", g2)
        except Exception as e:
            _update_layer(
                run_id, "L2", status="FAILED", error=str(e)[:500], finished_at=datetime.now(UTC)
            )
            _finish_run(run_id, success=False, error=f"L2 failed: {e}")
            return

        # 存 L0-L2 产物 → 供人工审核/续跑;pause_after=="L2" 则停在审核态,否则直接续渲染。
        _RUNS[run_id].update(
            {
                "req": req,
                "chapter_ir": chapter_ir,
                "constitution": constitution,
                "script": script,
                "run_dir": str(run_dir),
            }
        )
        _persist_review(run_dir, constitution, script)

        if req.pause_after == "L2":
            _RUNS[run_id]["status"] = "AWAITING_REVIEW"
            _RUNS[run_id]["current_layer"] = "L2"
            logger.info("tongjian run %s 出剧本完毕,暂停待人工审核(L2)", run_id)
            return

        await _run_render(run_id)

    except Exception as e:
        logger.exception("tongjian pipeline %s unhandled: %s", run_id, e)
        _finish_run(run_id, success=False, error=str(e)[:500])


async def _run_render(run_id: str) -> None:
    """续跑 L3-L8(审核通过后调用)。从 _RUNS 读回 L0-L2 产物(含人工编辑过的剧本)。"""
    from pathlib import Path

    rec = _RUNS[run_id]
    req: RunRequest = rec["req"]
    chapter_ir = rec["chapter_ir"]
    constitution = rec["constitution"]
    script = rec["script"]
    run_dir = Path(rec["run_dir"])
    rec["status"] = "RUNNING"

    try:
        from hevi.tongjian.voiceover import build_voiceover
        from hevi.tongjian.character_bible import generate_character_bible
        from hevi.tongjian.shotlist import build_shotlist
        from hevi.tongjian.scene_render import gate_frame_manifest, render_shots
        from hevi.tongjian.music_plan import build_music_plan
        from hevi.tongjian.assemble import build_final_video

        _llm, _tts, _params, _gate_done = _pipeline_helpers(run_id, req)

        # L3 配音 & L5 角色卡(并行)
        _update_layer(run_id, "L3", status="RUNNING", started_at=datetime.now(UTC))
        _update_layer(run_id, "L5", status="RUNNING", started_at=datetime.now(UTC))
        try:
            (timeline, g3), bible = await asyncio.gather(
                build_voiceover(
                    script=script,
                    constitution=constitution,
                    output_dir=run_dir / "L3",
                    tts_fn=_tts("L3"),
                ),
                generate_character_bible(
                    script=script, chapter_ir=chapter_ir, constitution=constitution, llm=_llm("L5")
                ),
            )
            _gate_done("L3", g3)
            _update_layer(run_id, "L5", status="PASSED", finished_at=datetime.now(UTC))
        except Exception as e:
            _update_layer(
                run_id, "L3", status="FAILED", error=str(e)[:500], finished_at=datetime.now(UTC)
            )
            _update_layer(
                run_id, "L5", status="FAILED", error=str(e)[:500], finished_at=datetime.now(UTC)
            )
            _finish_run(run_id, success=False, error=f"L3/L5 failed: {e}")
            return

        # L4 分镜。数字人管线每镜重生成音频,长 shot 拆子镜头会导致同句重复,故关闭拆分。
        _l6 = req.layer_config.get("L6")
        _is_avatar = bool(_l6 and _l6.model == "cloud_avatar")
        _update_layer(run_id, "L4", status="RUNNING", started_at=datetime.now(UTC))
        try:
            shotlist, g4 = await build_shotlist(
                timeline=timeline,
                script=script,
                character_bible=bible,
                llm=_llm("L4"),
                split_long_shots=not _is_avatar,
            )
            _gate_done("L4", g4)
        except Exception as e:
            _update_layer(
                run_id, "L4", status="FAILED", error=str(e)[:500], finished_at=datetime.now(UTC)
            )
            _finish_run(run_id, success=False, error=f"L4 failed: {e}")
            return

        # L6 场景/画面生成
        _update_layer(run_id, "L6", status="RUNNING", started_at=datetime.now(UTC))
        try:
            frame_manifest = await render_shots(
                shotlist=shotlist,
                character_bible=bible,
                constitution=constitution,
                run_dir=run_dir / "L6",
                script=script,  # cloud_avatar 渲染要取每镜台词
                config=req.layer_config.get("L6"),  # 选模型(sdxl_local/cloud_avatar)+ 参数
            )
            _l6 = req.layer_config.get("L6")
            if _l6 and _l6.model == "cloud_avatar":
                from hevi.tongjian.scene_render_avatar import gate_avatar_manifest

                _gate_done("L6", gate_avatar_manifest(frame_manifest))  # 语音/音画同步门
            else:
                _gate_done("L6", gate_frame_manifest(frame_manifest, shotlist))
        except Exception as e:
            _update_layer(
                run_id, "L6", status="FAILED", error=str(e)[:500], finished_at=datetime.now(UTC)
            )
            _finish_run(run_id, success=False, error=f"L6 failed: {e}")
            return

        # L7 音乐规划
        _update_layer(run_id, "L7", status="RUNNING", started_at=datetime.now(UTC))
        try:
            music_plan, g7 = await build_music_plan(
                shotlist=shotlist, timeline=timeline, constitution=constitution
            )
            _gate_done("L7", g7)
        except Exception as e:
            # L7 非致命,降级到无音乐
            _update_layer(
                run_id,
                "L7",
                status="DEGRADED",
                degraded=True,
                error=str(e)[:200],
                finished_at=datetime.now(UTC),
            )
            music_plan = None

        # L8 合成
        _update_layer(run_id, "L8", status="RUNNING", started_at=datetime.now(UTC))
        try:
            final_video, g8 = await build_final_video(
                shotlist=shotlist,
                frame_manifest=frame_manifest,
                timeline=timeline,
                script=script,
                music_plan=music_plan,
                constitution=constitution,
                audio_dir=run_dir / "L3",
                output_dir=run_dir / "L8",
            )
            _gate_done("L8", g8)
            _finish_run(run_id, success=True, result_path=final_video.video_path)
        except Exception as e:
            _update_layer(
                run_id, "L8", status="FAILED", error=str(e)[:500], finished_at=datetime.now(UTC)
            )
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


def _require_review_rec(run_id: str) -> dict[str, Any]:
    rec = _RUNS.get(run_id)
    if not rec:
        raise HTTPException(status_code=404, detail="run 不存在")
    if "script" not in rec or "constitution" not in rec:
        raise HTTPException(status_code=409, detail="剧本尚未生成,无法审核")
    return rec


@router.get("/runs/{run_id}/script")
async def get_run_script(
    run_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict[str, Any]:
    """取回待审核的立意+剧本(供人工审核台展示/编辑)。"""
    rec = _require_review_rec(run_id)
    return {
        "constitution": rec["constitution"].model_dump(),
        "script": rec["script"].model_dump(),
        "status": rec["status"],
    }


@router.put("/runs/{run_id}/script")
async def update_run_script(
    run_id: str,
    body: ScriptReviewUpdate,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict[str, str]:
    """人工审核提交:用编辑后的剧本(+可选立意)覆盖草稿。不触发续跑,只保存。

    line_id 一律由后端按顺序重排(LN001..),前端删行/加行/改顺序后不必自己管 id。
    """
    rec = _require_review_rec(run_id)
    if rec["status"] not in ("AWAITING_REVIEW", "COMPLETED", "FAILED"):
        raise HTTPException(status_code=409, detail=f"当前状态 {rec['status']} 不可编辑剧本")
    lines = []
    for i, ln in enumerate(body.script.lines, start=1):
        lines.append(ln.model_copy(update={"line_id": f"LN{i:03d}"}))
    rec["script"] = Script(lines=lines)
    if body.constitution is not None:
        rec["constitution"] = body.constitution
    from pathlib import Path

    _persist_review(Path(rec["run_dir"]), rec["constitution"], rec["script"])
    logger.info("tongjian run %s 剧本被人工编辑保存(%d 行)", run_id, len(lines))
    return {"run_id": run_id, "status": rec["status"], "lines": str(len(lines))}


@router.post("/runs/{run_id}/resume")
async def resume_run(
    run_id: str,
    background_tasks: BackgroundTasks,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict[str, str]:
    """审核通过 → 用(可能已编辑的)剧本续跑 L3-L8 渲染。"""
    rec = _require_review_rec(run_id)
    if rec["status"] != "AWAITING_REVIEW":
        raise HTTPException(status_code=409, detail=f"当前状态 {rec['status']} 不可续跑")
    rec["status"] = "RUNNING"
    background_tasks.add_task(_run_render, run_id)
    logger.info("tongjian run %s 审核通过,续跑渲染", run_id)
    return {"run_id": run_id, "status": "RUNNING"}


@router.post("/runs/{run_id}/regenerate")
async def regenerate_script(
    run_id: str,
    background_tasks: BackgroundTasks,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict[str, str]:
    """对剧本不满意 → 用同一 chapter_ir/立意 重出一版剧本(仍停在审核态)。"""
    rec = _require_review_rec(run_id)
    if rec["status"] != "AWAITING_REVIEW":
        raise HTTPException(status_code=409, detail=f"当前状态 {rec['status']} 不可重生成")

    async def _regen() -> None:
        from pathlib import Path

        from hevi.tongjian.script import build_script

        req: RunRequest = rec["req"]
        _llm, _tts, _params, _gate_done = _pipeline_helpers(run_id, req)
        _update_layer(run_id, "L2", status="RUNNING", started_at=datetime.now(UTC))
        try:
            script, g2 = await build_script(
                chapter_ir=rec["chapter_ir"],
                constitution=rec["constitution"],
                llm=_llm("L2"),
                dramatize=bool(_params("L2").get("dramatize", True)),
            )
            rec["script"] = script
            _gate_done("L2", g2)
            _persist_review(Path(rec["run_dir"]), rec["constitution"], script)
        except Exception as e:  # noqa: BLE001
            logger.warning("tongjian run %s 重生成剧本失败: %s", run_id, e)
        rec["status"] = "AWAITING_REVIEW"

    rec["status"] = "RUNNING"
    background_tasks.add_task(_regen)
    return {"run_id": run_id, "status": "RUNNING"}


@router.get("/runs/{run_id}/video")
async def download_run_video(
    run_id: str,
    token: Annotated[str | None, Query(description="JWT (<video>/<a> 不能带 header)")] = None,
) -> FileResponse:
    """取回某次 run 的成片(final.mp4)。

    <video src>/<a download> 无法带 Authorization 头,故 JWT 走 ?token= 校验。
    直接按确定性路径 output/tongjian/<run_id>/L8/final.mp4 取片,不依赖内存 _RUNS,
    这样即使 API 重启(内存 run 记录丢失)历史成片仍可下载。
    """
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        user_id = decode_access_token(token).get("sub")
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # run_id 来自 URL,必须是合法 UUID,防止路径穿越
    try:
        uuid.UUID(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="非法 run_id") from exc

    path = Path("output/tongjian") / run_id / "L8" / "final.mp4"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="成片不存在或已被清理")
    return FileResponse(path, media_type="video/mp4", filename=f"tongjian_{run_id[:8]}.mp4")


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
