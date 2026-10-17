"""production_tools API —— 对标 OpenMontage 的新能力入口。

整合所有新增模块的 HTTP 端点:
  - POST /production/reference-analyze    参考视频分析
  - GET  /production/stock/search         Stock footage 检索
  - POST /production/enhance/{tool}       图像增强(upscale/bg_remove/face_restore/color_grade)
  - GET  /production/playbooks            列出 Playbooks
  - POST /production/render/remotion      Remotion 合成
  - POST /production/edit/talking-head-cleanup  剪辑成片层：去 filler
  - POST /production/edit/render-edl      剪辑成片层：EDL 渲染+自检
  - GET  /production/media-profiles       多平台 Profile 列表
  - GET  /production/backlot/{task_id}    Backlot 制片看板数据

与 director_pipeline / tongjian 路由平行,不互相依赖。
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/production", tags=["production-tools"])


# ── 参考视频分析 ─────────────────────────────────────────────────────────────

class ReferenceAnalyzeRequest(BaseModel):
    video_url: str | None = None
    generate_concepts: bool = True


@router.post("/reference-analyze")
async def analyze_reference(
    req: ReferenceAnalyzeRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """分析参考视频 → 节奏/场景/风格/概念。"""
    from hevi.analysis.reference_video import analyze_reference_video

    if not req.video_url:
        raise HTTPException(400, "video_url is required")

    output_dir = Path(tempfile.mkdtemp(prefix="ref_analysis_"))

    # 后台执行,避免阻塞
    task_id = f"ref_{hash(req.video_url) % 100000}"

    async def _run():
        try:
            await analyze_reference_video(
                Path(req.video_url), output_dir,
                generate_concepts=req.generate_concepts,
            )
        except Exception as e:
            logger.error("Reference analysis failed: %s", e)

    background_tasks.add_task(_run)
    return {"task_id": task_id, "status": "started", "output_dir": str(output_dir)}


# ── Stock footage 检索 ───────────────────────────────────────────────────────

@router.get("/stock/search")
async def search_stock(
    query: str = Query(..., description="搜索词"),
    provider: str = Query("pexels", description="pexels/pixabay/unsplash"),
    per_page: int = Query(5, ge=1, le=20),
    orientation: str = Query("portrait", description="portrait/landscape/square"),
) -> dict[str, Any]:
    """搜索 stock footage(不下载,只返回 URL + 元数据)。"""
    from hevi.image.stock_footage import search_stock

    clips = await search_stock(
        query, provider=provider, per_page=per_page, orientation=orientation,
    )
    return {
        "query": query,
        "provider": provider,
        "count": len(clips),
        "clips": [
            {
                "url": c.url,
                "provider": c.provider,
                "width": c.width,
                "height": c.height,
                "duration_s": c.duration_s,
                "license": c.license,
            }
            for c in clips
        ],
    }


@router.get("/stock/match")
async def match_stock(
    caption: str = Query(..., description="镜头描述"),
    clip_url: str = Query("", description="素材 URL(可选)"),
    clip_description: str = Query("", description="素材描述"),
) -> dict[str, Any]:
    """计算 caption 与素材的对位分。"""
    from hevi.image.stock_footage import score_match

    result = score_match(caption, clip_description=clip_description)
    return {
        "score": result.score,
        "matched_keywords": result.matched_keywords,
        "missed_keywords": result.missed_keywords,
        "eligible": result.score >= 0.3,
    }


# ── 图像增强 ────────────────────────────────────────────────────────────────

class EnhanceRequest(BaseModel):
    tool: str = Field(..., description="upscale/bg_remove/face_restore/color_grade")
    params: dict[str, Any] = Field(default_factory=dict)


@router.post("/enhance/{tool}")
async def enhance_image(
    tool: str,
    file: UploadFile,
    params: str = Query("{}", description="JSON 参数"),
) -> dict[str, Any]:
    """图像增强后处理。"""
    import json

    from hevi.enhancement import color_grade, remove_background, restore_face, upscale

    param_dict = json.loads(params) if params != "{}" else {}
    work_dir = Path(tempfile.mkdtemp(prefix="enhance_"))
    src = work_dir / f"input{Path(file.filename or 'img.png').suffix}"

    content = await file.read()
    src.write_bytes(content)

    dst = work_dir / f"output_{tool}.png"

    try:
        if tool == "upscale":
            upscale(src, dst, **param_dict)
        elif tool == "bg_remove":
            remove_background(src, dst, **param_dict)
        elif tool == "face_restore":
            restore_face(src, dst, **param_dict)
        elif tool == "color_grade":
            color_grade(src, dst, **param_dict)
        else:
            raise HTTPException(400, f"Unknown tool: {tool}") from None
    except Exception as e:
        raise HTTPException(500, f"Enhancement failed: {e}") from e

    from fastapi.responses import FileResponse
    return FileResponse(str(dst), media_type="image/png", filename=f"enhanced_{tool}.png")


# ── Playbook ─────────────────────────────────────────────────────────────────

@router.get("/playbooks")
async def list_playbooks() -> dict[str, Any]:
    """列出所有可用 StylePack Playbook。"""
    from hevi.style.playbook_loader import list_playbooks
    return {"playbooks": list_playbooks()}


class CompilePromptRequest(BaseModel):
    playbook_id: str
    provider: str = ""
    genre: str = "drama"
    scene_description: str = ""


@router.post("/playbooks/compile")
async def compile_playbook_prompt(req: CompilePromptRequest) -> dict[str, Any]:
    """将 Playbook 编译成 provider 适配的 prompt 组件。"""
    from hevi.style.playbook_loader import (
        _BUILTIN_DEVICE_PACKS,
        compile_prompt,
        load_playbook_from_dict,
    )

    # 先查内置设备包
    if req.playbook_id in _BUILTIN_DEVICE_PACKS:
        dp = _BUILTIN_DEVICE_PACKS[req.playbook_id]
        pb = load_playbook_from_dict({
            "id": dp.id,
            "capture_source": dp.capture_source,
            "device_pack": dp.id,
        })
    else:
        raise HTTPException(404, f"Playbook not found: {req.playbook_id}")

    return compile_prompt(pb, provider=req.provider, genre=req.genre,
                          scene_description=req.scene_description)


# ── Remotion 合成 ────────────────────────────────────────────────────────────

class RemotionRenderRequest(BaseModel):
    manifest: dict[str, Any]
    composition: str = "ExplainerVideo"
    width: int = 1920
    height: int = 1080
    fps: int = 30


@router.post("/render/remotion")
async def render_remotion(
    req: RemotionRenderRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """通过 Remotion 程序化合成视频(后台任务)。"""
    task_id = f"remotion_{hash(str(req.manifest)) % 100000}"
    output_dir = Path(f"output/remotion/{task_id}")
    output = output_dir / "final.mp4"

    async def _render():
        from hevi.video.remotion_service import render_remotion
        try:
            render_remotion(req.manifest, output,
                           composition=req.composition,
                           width=req.width, height=req.height, fps=req.fps)
        except Exception as e:
            logger.error("Remotion render failed: %s", e)

    background_tasks.add_task(_render)
    return {"task_id": task_id, "status": "started", "output_path": str(output)}


# ── 剪辑成片层（edit craft / talking-head cleanup）──────────────────────────

class TalkingHeadCleanupRequest(BaseModel):
    source_video: str = Field(..., description="源视频绝对/相对路径")
    transcript_path: str | None = Field(None, description="词级 transcript JSON 路径")
    transcript: dict[str, Any] | None = Field(None, description="或直接传 transcript JSON")
    work_dir: str = Field(..., description="工作目录，输出进 work_dir/edit/")
    strategy_confirmed: bool = False
    preview: bool = True
    strong_fillers_only: bool = True


@router.post("/edit/talking-head-cleanup")
async def talking_head_cleanup_api(req: TalkingHeadCleanupRequest) -> dict[str, Any]:
    """去 filler/压静音选切。strategy_confirmed=false 只出方案；true 才渲染。"""
    from hevi.assembly.edit_pipeline import talking_head_cleanup

    src = Path(req.source_video)
    if not src.exists():
        raise HTTPException(400, f"source_video not found: {req.source_video}")
    if req.transcript is None and not req.transcript_path:
        raise HTTPException(400, "transcript or transcript_path required")
    transcript: Any
    if req.transcript is not None:
        transcript = req.transcript
    else:
        tp = Path(req.transcript_path or "")
        if not tp.exists():
            raise HTTPException(400, f"transcript_path not found: {req.transcript_path}")
        transcript = tp
    try:
        return await talking_head_cleanup(
            source_video=src,
            transcript=transcript,
            work_dir=Path(req.work_dir),
            strategy_confirmed=req.strategy_confirmed,
            preview=req.preview,
            strong_fillers_only=req.strong_fillers_only,
        )
    except Exception as e:
        logger.exception("talking-head cleanup failed")
        raise HTTPException(400, str(e)) from e


class EditCraftRenderRequest(BaseModel):
    videos_dir: str
    edl: dict[str, Any]
    strategy_confirmed: bool | None = None
    preview: bool = True
    skip_render: bool = False


@router.post("/edit/render-edl")
async def render_edl_api(req: EditCraftRenderRequest) -> dict[str, Any]:
    """按 EDL 渲染（硬规则 + 自检）。须 strategy_confirmed。"""
    from hevi.skills.edit_craft import edit_craft_skill_execute

    try:
        return await edit_craft_skill_execute(
            videos_dir=req.videos_dir,
            edl=req.edl,
            strategy_confirmed=req.strategy_confirmed,
            preview=req.preview,
            skip_render=req.skip_render,
        )
    except Exception as e:
        logger.exception("edit craft render failed")
        raise HTTPException(400, str(e)) from e


# ── Media Profiles ───────────────────────────────────────────────────────────

@router.get("/media-profiles")
async def list_media_profiles() -> dict[str, Any]:
    """列出所有多平台 Media Profile。"""
    from hevi.video.media_profiles import list_profiles
    profiles = list_profiles()
    return {
        "profiles": [
            {
                "name": p.name,
                "width": p.width,
                "height": p.height,
                "aspect": p.aspect,
                "max_duration_s": p.max_duration_s,
                "fps": p.fps,
                "notes": p.notes,
            }
            for p in profiles
        ],
    }


@router.get("/media-profiles/{name}/ffmpeg-args")
async def get_ffmpeg_args(name: str) -> dict[str, Any]:
    """获取某 profile 的 ffmpeg 输出参数。"""
    from hevi.video.media_profiles import ffmpeg_output_args, get_media_profile
    profile = get_media_profile(name)
    return {"profile": profile.name, "ffmpeg_args": ffmpeg_output_args(profile)}


# ── Backlot 看板数据 ─────────────────────────────────────────────────────────

@router.get("/backlot/{task_id}")
async def get_backlot_data(task_id: str) -> dict[str, Any]:
    """获取制片看板数据(对标 OpenMontage Backlot)。

    从 task 状态 + shot_states + verdict 聚合出:
      - 阶段进度灯(stage_rail)
      - 场景卡片列表(scene_cards)
      - 成本仪表(cost_meter)
      - 决策日志(decision_log)
    """
    from hevi.db.pg_pool import get_hevi_pg_pool
    from hevi.tasks.repository import TaskRepository

    pool = await get_hevi_pg_pool()
    repo = TaskRepository(pool)
    task = await repo.get_task(task_id)
    if not task:
        raise HTTPException(404, f"Task not found: {task_id}")

    shots = await repo.get_shot_states(task_id)

    # 构造 Backlot 数据
    stage_rail = _build_stage_rail(task, shots)
    scene_cards = _build_scene_cards(shots)
    cost_meter = _build_cost_meter(task)

    return {
        "task_id": task_id,
        "title": task.get("title", task_id),
        "status": task.get("status", "unknown"),
        "stage_rail": stage_rail,
        "scene_cards": scene_cards,
        "cost_meter": cost_meter,
        "created_at": str(task.get("created_at", "")),
    }


def _build_stage_rail(task: dict, shots: list[dict]) -> list[dict]:
    """构建阶段进度灯。"""
    stages = ["research", "proposal", "script", "scene_plan", "assets", "edit", "compose"]
    current = task.get("current_stage", "")
    status = task.get("status", "")

    rail = []
    for s in stages:
        if s == current and status not in ("completed", "failed"):
            state = "active"
        elif (
            (current in stages and stages.index(s) < stages.index(current))
            or status == "completed"
        ):
            state = "completed"
        else:
            state = "pending"
        rail.append({"stage": s, "state": state})
    return rail


def _build_scene_cards(shots: list[dict]) -> list[dict]:
    """构建场景卡片列表。"""
    return [
        {
            "shot_id": shot.get("shot_id", shot.get("id", "")),
            "index": shot.get("order", 0),
            "status": shot.get("status", "pending"),
            "provider": shot.get("provider", ""),
            "duration_s": shot.get("duration_s", 0),
            "video_path": shot.get("result_path", ""),
        }
        for shot in shots
    ]


def _build_cost_meter(task: dict) -> dict[str, Any]:
    """构建成本仪表。"""
    return {
        "estimated_usd": task.get("estimated_usd", 0),
        "actual_usd": task.get("actual_usd", 0),
        "budget_usd": task.get("budget_usd", 10.0),
        "remaining_usd": task.get("budget_usd", 10.0) - task.get("actual_usd", 0),
    }
