"""Production Tools V2 compatibility surface.

These endpoints keep the workbench usable while provider-specific rendering is
routed through the canonical production/task pipeline.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from obase.persistence import PgPool
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.credits.account_service import AccountService
from hevi.credits.billing_service import BillingService, InsufficientCredits
from hevi.credits.repository import CreditRepository
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.production.contracts import ProductionRequest
from hevi.tasks.dispatch import schedule_local_compat
from hevi.tasks.repository import TaskRepository
from hevi.tasks.task_service import TaskService

router = APIRouter(prefix="/production/v2", tags=["production-v2"])


async def get_task_service() -> TaskService:
    pool: PgPool = await get_hevi_pg_pool()
    return TaskService(TaskRepository(pool), BillingService(AccountService(CreditRepository(pool))))


async def _create_task(
    *,
    user: dict[str, Any],
    service: TaskService,
    background_tasks: BackgroundTasks,
    topic: str,
    source: Literal["automatic", "explainer"],
    presenter_id: str | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        task = await service.create_production(
            ProductionRequest(
                source=source,
                topic=topic,
                duration_archetype="1-5min",
                video_provider="auto",
                audio_provider="edge_tts",
                presenter_id=presenter_id,
                options=options or {},
            ),
            user_id=str(user["id"]),
        )
        task = await service.submit_task(task["id"])
    except InsufficientCredits as exc:
        raise HTTPException(
            status_code=402,
            detail={"error": "insufficient_credits", "credits_needed": exc.credits_needed},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if task.get("status") != "queued":
        schedule_local_compat(background_tasks, service, task["id"])
    return {
        "task_id": str(task["id"]),
        "status": task["status"],
        "production_source": source,
        "status_url": f"/api/tasks/{task['id']}",
        "download_url": f"/api/tasks/{task['id']}/download",
    }


class SeedanceRequest(BaseModel):
    prompt: str = ""
    mode: str = "t2v"
    duration_s: int = Field(default=5, ge=1, le=60)
    resolution: str = "720p"
    aspect_ratio: str = "16:9"
    image_url: str | None = None


class ClipRequest(BaseModel):
    video_path: str
    strategy: str = "viral"
    max_clips: int = Field(default=5, ge=1, le=20)


class DigitalHumanRequest(BaseModel):
    script: str = ""
    avatar_id: str | None = None


class RecipeExecuteRequest(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)


_RECIPES = [
    {
        "name": "short_explainer",
        "description": "解说词、字幕、配音与竖屏交付",
        "category": "解说",
        "steps_count": 4,
        "estimated_duration_s": 90,
        "estimated_cost_usd": 0,
    },
    {
        "name": "digital_presenter",
        "description": "数字人预检、口播与画中画交付",
        "category": "数字人",
        "steps_count": 5,
        "estimated_duration_s": 120,
        "estimated_cost_usd": 0,
    },
]


@router.post("/seedance/generate")
async def seedance(
    body: SeedanceRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[TaskService, Depends(get_task_service)],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    if not body.prompt.strip():
        raise HTTPException(status_code=422, detail="prompt 不能为空")
    return await _create_task(
        user=user,
        service=service,
        background_tasks=background_tasks,
        topic=body.prompt,
        source="automatic",
        options={
            "workbench_operation": "seedance_generate",
            "seedance_mode": body.mode,
            "requested_duration_s": body.duration_s,
            "requested_resolution": body.resolution,
            "requested_aspect_ratio": body.aspect_ratio,
            "source_image_url": body.image_url,
        },
    )


@router.post("/clip-video")
async def clip_video(
    body: ClipRequest, _: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    raise HTTPException(
        status_code=503,
        detail={
            "code": "CAPABILITY_UNAVAILABLE",
            "capability_id": "clip_video",
            "message": "智能切片事务尚未接入，不能把原视频伪装成已剪辑成片。",
            "setup": "接入可验证的剪辑 operation 和 ArtifactManifest 后开放。",
        },
    )


@router.get("/recipes")
async def list_recipes(_: Annotated[dict[str, Any], Depends(get_current_user)]) -> dict[str, Any]:
    return {"recipes": _RECIPES}


@router.get("/recipes/{name}")
async def get_recipe(
    name: str, _: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    recipe = next(
        (item for item in _RECIPES if item["name"] == name),
        {"name": name, "description": "自定义统一生产配方"},
    )
    return {
        **recipe,
        "inputs": {"topic": "主题或材料", "presenter_id": "可选数字人预设"},
        "outputs": {"task_id": "统一 Task ID"},
        "steps": [{"step_type": "task", "description": "交给统一 Task 执行器", "optional": False}],
        "tags": ["canonical", "task"],
    }


@router.post("/recipes/{name}/execute")
async def execute_recipe(
    name: str,
    body: RecipeExecuteRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[TaskService, Depends(get_task_service)],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    topic = str(body.params.get("topic") or body.params.get("script") or "").strip()
    if not topic:
        raise HTTPException(status_code=422, detail="params.topic 或 params.script 不能为空")
    if name == "short_explainer":
        return await _create_task(
            user=user,
            service=service,
            background_tasks=background_tasks,
            topic=topic,
            source="explainer",
            options={"workbench_recipe": name, "recipe_params": body.params},
        )
    if name == "digital_presenter":
        return await _create_task(
            user=user,
            service=service,
            background_tasks=background_tasks,
            topic=topic,
            source="automatic",
            presenter_id=body.params.get("presenter_id"),
            options={"workbench_recipe": name, "avatar_id": body.params.get("avatar_id")},
        )
    raise HTTPException(status_code=404, detail="未知生产配方")


@router.post("/digital-human/preflight")
async def digital_human_preflight(
    body: DigitalHumanRequest, _: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    warnings = [] if body.avatar_id else ["未绑定 Presenter/Avatar，将降级为旁白模式"]
    return {
        "ready": bool(body.script.strip()),
        "ok": bool(body.script.strip()),
        "warnings": warnings,
        "errors": [] if body.script.strip() else ["脚本不能为空"],
        "script_chars": len(body.script),
    }


@router.post("/digital-human/preview")
async def digital_human_preview(
    body: DigitalHumanRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[TaskService, Depends(get_task_service)],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    if not body.script.strip():
        raise HTTPException(status_code=422, detail="脚本不能为空")
    return await _create_task(
        user=user,
        service=service,
        background_tasks=background_tasks,
        topic=body.script,
        source="automatic",
        presenter_id=body.avatar_id,
        options={"workbench_operation": "digital_human_preview", "preview": True},
    )


@router.post("/digital-human/approve")
async def digital_human_approve(
    body: dict[str, Any],
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[TaskService, Depends(get_task_service)],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    script = str(body.get("script") or "").strip()
    if not script:
        raise HTTPException(status_code=422, detail="脚本不能为空")
    return await _create_task(
        user=user,
        service=service,
        background_tasks=background_tasks,
        topic=script,
        source="automatic",
        presenter_id=body.get("avatar_id") or body.get("presenter_id"),
        options={"workbench_operation": "digital_human_approve", "preview_task_id": body.get("task_id")},
    )
