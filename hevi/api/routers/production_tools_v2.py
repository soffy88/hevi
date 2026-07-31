"""Production Tools V2 API —— Seedance 2 / 视频拆条 / Recipe Pack / 数字人预览。

端点:
- POST /production/v2/seedance/generate       — Seedance 2 视频生成(t2v/i2v/extend)
- POST /production/v2/clip-video              — 长视频→短视频拆条
- GET  /production/v2/recipes                 — 列出工作流配方
- GET  /production/v2/recipes/{name}          — 获取单个配方
- POST /production/v2/recipes/{name}/execute  — 执行配方
- POST /production/v2/digital-human/preflight  — 数字人资产预检
- POST /production/v2/digital-human/preview    — 生成 15s 预览
- POST /production/v2/digital-human/approve    — 确认预览
- POST /production/v2/digital-human/generate   — 生成完整视频
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from hevi.auth.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/production/v2", tags=["production-v2"])


# ── Seedance 2 ────────────────────────────────────────────────────────────


class SeedanceRequest(BaseModel):
    prompt: str
    mode: str = "t2v"  # t2v / i2v / extend
    duration_s: int = 5
    resolution: str = "720p"
    aspect_ratio: str = "16:9"
    image_url: str | None = None
    extend_request_id: str | None = None
    seed: int | None = None


@router.post("/seedance/generate")
async def seedance_generate(
    body: SeedanceRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Seedance 2 视频生成。"""
    from hevi.video.provider_seedance import generate_seedance_clip

    output_dir = Path("output/seedance")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"seedance_{body.mode}.mp4"

    try:
        result = await generate_seedance_clip(
            prompt=body.prompt,
            output_path=output_path,
            mode=body.mode,
            duration_s=body.duration_s,
            resolution=body.resolution,
            aspect_ratio=body.aspect_ratio,
            image_url=body.image_url,
            extend_request_id=body.extend_request_id,
            seed=body.seed,
        )
        return {
            "request_id": result.request_id,
            "video_url": result.video_url,
            "local_path": str(result.local_path),
            "duration_s": result.duration_s,
            "cost_usd": result.cost_usd,
            "mode": result.mode,
            "audio_url": result.audio_url,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 视频拆条 ─────────────────────────────────────────────────────────────


class ClipVideoRequest(BaseModel):
    video_path: str
    num_clips: int = 5
    aspect_ratio: str = "9:16"
    coords_only: bool = False


@router.post("/clip-video")
async def clip_video(
    body: ClipVideoRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """长视频→短视频智能拆条。"""
    from hevi.video.video_clipper import clip_long_video

    input_path = Path(body.video_path)
    if not input_path.exists():
        raise HTTPException(status_code=404, detail=f"Video not found: {body.video_path}")

    result = await clip_long_video(
        input_path=input_path,
        num_clips=body.num_clips,
        aspect_ratio=body.aspect_ratio,
        coords_only=body.coords_only,
    )

    if result.error:
        raise HTTPException(status_code=500, detail=result.error)

    return {
        "source_path": str(result.source_path),
        "total_duration_s": result.total_duration_s,
        "num_clips": len(result.clips),
        "clips": [
            {
                "start_time": c.start_time,
                "end_time": c.end_time,
                "score": c.score,
                "title": c.title,
                "hook_sentence": c.hook_sentence,
                "virality_reason": c.virality_reason,
                "category": c.category,
                "clip_path": str(c.clip_path) if c.clip_path else None,
            }
            for c in result.clips
        ],
    }


@router.post("/clip-video/upload")
async def clip_video_upload(
    file: Annotated[UploadFile, File(description="长视频文件")],
    num_clips: int = 5,
    aspect_ratio: str = "9:16",
    user: Annotated[dict[str, Any], Depends(get_current_user)] | None = None,
) -> dict[str, Any]:
    """上传长视频并拆条。"""
    from hevi.video.video_clipper import clip_long_video

    # 保存到临时文件
    upload_dir = Path("output/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "video.mp4").suffix or ".mp4"
    temp_path = upload_dir / f"clip_upload_{id(file)}{suffix}"

    data = await file.read()
    temp_path.write_bytes(data)

    try:
        result = await clip_long_video(
            input_path=temp_path,
            num_clips=num_clips,
            aspect_ratio=aspect_ratio,
        )
        if result.error:
            raise HTTPException(status_code=500, detail=result.error)

        return {
            "source_path": str(result.source_path),
            "total_duration_s": result.total_duration_s,
            "num_clips": len(result.clips),
            "clips": [
                {
                    "start_time": c.start_time,
                    "end_time": c.end_time,
                    "score": c.score,
                    "title": c.title,
                    "hook_sentence": c.hook_sentence,
                    "virality_reason": c.virality_reason,
                    "category": c.category,
                    "clip_path": str(c.clip_path) if c.clip_path else None,
                }
                for c in result.clips
            ],
        }
    finally:
        # 清理临时文件（可选保留）
        if temp_path.exists():
            temp_path.unlink()


# ── Recipe Pack ──────────────────────────────────────────────────────────


@router.get("/recipes")
async def list_recipes(
    category: str | None = None,
    user: Annotated[dict[str, Any], Depends(get_current_user)] | None = None,
) -> dict[str, Any]:
    """列出可用的工作流配方。"""
    from hevi.video.recipe_pack import list_recipes as _list, list_recipe_categories

    recipes = _list(category=category)
    return {
        "recipes": [
            {
                "name": r.name,
                "description": r.description,
                "category": r.category,
                "inputs": r.inputs,
                "outputs": r.outputs,
                "estimated_duration_s": r.estimated_duration_s,
                "estimated_cost_usd": r.estimated_cost_usd,
                "tags": r.tags,
                "steps_count": len(r.steps),
            }
            for r in recipes
        ],
        "total": len(recipes),
        "categories": list_recipe_categories(),
    }


@router.get("/recipes/{name}")
async def get_recipe(
    name: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)] | None = None,
) -> dict[str, Any]:
    """获取单个配方详情。"""
    from hevi.video.recipe_pack import get_recipe as _get

    recipe = _get(name)
    if not recipe:
        raise HTTPException(status_code=404, detail=f"Recipe not found: {name}")

    return {
        "name": recipe.name,
        "description": recipe.description,
        "category": recipe.category,
        "inputs": recipe.inputs,
        "outputs": recipe.outputs,
        "steps": [
            {
                "step_type": s.step_type.value,
                "description": s.description,
                "input_keys": s.input_keys,
                "output_key": s.output_key,
                "optional": s.optional,
            }
            for s in recipe.steps
        ],
        "estimated_duration_s": recipe.estimated_duration_s,
        "estimated_cost_usd": recipe.estimated_cost_usd,
        "tags": recipe.tags,
    }


class RecipeExecuteRequest(BaseModel):
    inputs: dict[str, Any] = {}


@router.post("/recipes/{name}/execute")
async def execute_recipe(
    name: str,
    body: RecipeExecuteRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """执行工作流配方。"""
    from hevi.video.recipe_pack import get_recipe as _get

    recipe = _get(name)
    if not recipe:
        raise HTTPException(status_code=404, detail=f"Recipe not found: {name}")

    try:
        results = await recipe.execute(body.inputs)
        # 序列化结果（Path → str）
        serialized = {}
        for k, v in results.items():
            if isinstance(v, Path):
                serialized[k] = str(v)
            elif hasattr(v, "__dict__"):
                serialized[k] = {kk: str(vv) if isinstance(vv, Path) else vv
                                 for kk, vv in v.__dict__.items()}
            else:
                serialized[k] = v
        return {"recipe": name, "results": serialized}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Digital Human Preview ────────────────────────────────────────────────


class PreflightRequest(BaseModel):
    project: str
    script_text: str | None = None


@router.post("/digital-human/preflight")
async def digital_human_preflight(
    body: PreflightRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """数字人资产预检。"""
    from hevi.video.digital_human_preview import DigitalHumanPipeline

    pipeline = DigitalHumanPipeline()
    result = pipeline.preflight(script_text=body.script_text)
    return {
        "ok": result.ok,
        "errors": result.errors,
        "warnings": result.warnings,
        "script_chars": result.script_chars,
    }


class PreviewRequest(BaseModel):
    project: str
    portrait_path: str
    script_text: str
    duration_s: int = 15


@router.post("/digital-human/preview")
async def digital_human_preview(
    body: PreviewRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """生成 15s 数字人预览。"""
    from hevi.video.digital_human_preview import DigitalHumanPipeline

    pipeline = DigitalHumanPipeline()
    portrait = Path(body.portrait_path)
    if not portrait.exists():
        raise HTTPException(status_code=404, detail="Portrait not found")

    job = await pipeline.generate_preview(
        project=body.project,
        portrait_path=portrait,
        script_text=body.script_text,
        duration_s=body.duration_s,
    )
    return job.to_dict()


class ApproveRequest(BaseModel):
    project: str


@router.post("/digital-human/approve")
async def digital_human_approve(
    body: ApproveRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """确认预览，允许生成完整视频。"""
    from hevi.video.digital_human_preview import DigitalHumanPipeline

    pipeline = DigitalHumanPipeline()
    try:
        job = pipeline.approve_preview(body.project)
        return job.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


class GenerateFullRequest(BaseModel):
    project: str
    portrait_path: str
    script_text: str
    duration_s: int = 60


@router.post("/digital-human/generate")
async def digital_human_generate(
    body: GenerateFullRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """生成完整 1080p 数字人视频（需先确认预览）。"""
    from hevi.video.digital_human_preview import DigitalHumanPipeline

    pipeline = DigitalHumanPipeline()
    portrait = Path(body.portrait_path)
    if not portrait.exists():
        raise HTTPException(status_code=404, detail="Portrait not found")

    try:
        job = await pipeline.generate_full(
            project=body.project,
            portrait_path=portrait,
            script_text=body.script_text,
            duration_s=body.duration_s,
        )
        return job.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
