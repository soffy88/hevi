"""MoneyPrinterTurbo 集成路由 - hevi 暴露的 MPT 能力端点

hevi 作为编排中枢，代理调用 MPT 服务（素材/生成/发布/参考视频分析）。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.credits.account_service import AccountService
from hevi.credits.billing_service import BillingService, InsufficientCredits
from hevi.credits.repository import CreditRepository
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.production.contracts import ProductionRequest
from hevi.provider_policy.runtime import probe_provider
from hevi.services.mpt_integration import MPTClient, submit_mpt_job_from_hevi
from hevi.tasks.dispatch import schedule_local_compat
from hevi.tasks.repository import TaskRepository
from hevi.tasks.task_service import TaskService

router = APIRouter(prefix="/mpt", tags=["mpt"])


class GenerateVideoRequest(BaseModel):
    topic: str
    video_count: int = Field(default=1, ge=1, le=10)
    aspect: str = Field(default="9:16", pattern=r"^(16:9|9:16|1:1|4:3|3:4)$")
    voice: str = "zh-CN-XiaoxiaoNeural"
    bgm: bool = True
    subtitle: bool = True
    material_mode: str = Field(default="pexels", pattern=r"^(pexels|pixabay|local)$")


class GenerateVideoResponse(BaseModel):
    task_id: str
    status: str
    message: str


class TaskStatusResponse(BaseModel):
    task_id: str
    state: str
    progress: int = 0
    videos: list[str] = Field(default_factory=list)
    error: str | None = None


class MaterialSearchRequest(BaseModel):
    query: str
    source: str = Field(default="pexels", pattern=r"^(pexels|pixabay)$")
    count: int = Field(default=10, ge=1, le=50)
    min_duration: int = Field(default=5, ge=1)


class MaterialItem(BaseModel):
    url: str
    duration: float
    width: int
    height: int
    source: str
    thumbnail: str | None = None


class CrossPostRequest(BaseModel):
    video_path: str
    title: str
    platforms: list[str]


class ReferenceVideoRequest(BaseModel):
    url: str


class ReferenceVideoResponse(BaseModel):
    transcript: str
    rhythm_analysis: dict[str, Any]
    scene_breakdown: list[dict[str, Any]]
    concepts: list[dict[str, Any]]


def get_mpt_client() -> MPTClient:
    return MPTClient()


MPTClientDependency = Annotated[MPTClient, Depends(get_mpt_client)]


async def _require_mpt_ready() -> dict[str, Any]:
    status = await probe_provider("mpt", timeout_s=3.0)
    if not status["ready"]:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "PROVIDER_UNAVAILABLE",
                "provider": "mpt",
                "message": "MPT API 当前不可达，未创建任务。",
                "provider_status": status,
            },
        )
    return status


async def get_mpt_task_service() -> TaskService:
    pool = await get_hevi_pg_pool()
    return TaskService(TaskRepository(pool), BillingService(AccountService(CreditRepository(pool))))


@router.post("/production", response_model=GenerateVideoResponse)
async def create_canonical_mpt_production(
    request: GenerateVideoRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[TaskService, Depends(get_mpt_task_service)],
    background_tasks: BackgroundTasks,
) -> GenerateVideoResponse:
    """Create MPT work as a canonical Hevi Task."""

    await _require_mpt_ready()
    try:
        task = await service.create_production(
            ProductionRequest(
                source="mpt",
                topic=request.topic,
                duration_archetype="1-5min",
                video_provider="mpt_cloud",
                audio_provider="none",
                aspect_ratio=request.aspect,
                options={
                    "workbench_operation": "mpt_generate",
                    "mpt_request": request.model_dump(mode="json"),
                },
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
    return GenerateVideoResponse(
        task_id=str(task["id"]),
        status=str(task.get("status") or "pending"),
        message="Hevi canonical task created; MPT output will be committed as artifacts",
    )


@router.post("/generate", response_model=GenerateVideoResponse)
async def generate_video(
    request: GenerateVideoRequest,
    client: MPTClientDependency,
) -> GenerateVideoResponse:
    """提交视频生成任务到 MPT"""
    await _require_mpt_ready()
    async with client:
        result = await client.generate_video(
            topic=request.topic,
            video_count=request.video_count,
            aspect=request.aspect,
            voice=request.voice,
            bgm=request.bgm,
            subtitle=request.subtitle,
            material_mode=request.material_mode,
        )
    return GenerateVideoResponse(
        task_id=result.get("task_id", ""),
        status="submitted",
        message="Task submitted to MPT",
    )


@router.get("/status/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: str,
    client: MPTClientDependency,
) -> TaskStatusResponse:
    """查询 MPT 任务状态"""
    await _require_mpt_ready()
    async with client:
        result = await client.check_task_status(task_id)
    return TaskStatusResponse(
        task_id=task_id,
        state=result.get("state", "unknown"),
        progress=result.get("progress", 0),
        videos=result.get("videos", []),
        error=result.get("error"),
    )


@router.post("/material/search", response_model=list[MaterialItem])
async def search_materials(
    request: MaterialSearchRequest,
    client: MPTClientDependency,
) -> list[MaterialItem]:
    """搜索素材（代理 MPT 素材搜索能力）"""
    await _require_mpt_ready()
    async with client:
        materials = await client.get_materials(
            query=request.query,
            source=request.source,
            count=request.count,
            min_duration=request.min_duration,
        )
    return [MaterialItem(**m) for m in materials]


@router.post("/cross-post", response_model=dict[str, Any])
async def cross_post(
    request: CrossPostRequest,
    client: MPTClientDependency,
) -> dict[str, Any]:
    """一键发布到多平台"""
    await _require_mpt_ready()
    async with client:
        return await client.cross_post(
            video_path=request.video_path,
            title=request.title,
            platforms=request.platforms,
        )


@router.post("/reference/analyze", response_model=ReferenceVideoResponse)
async def analyze_reference_video(
    request: ReferenceVideoRequest,
    client: MPTClientDependency,
) -> ReferenceVideoResponse:
    """参考视频分析（转录/节奏/场景/概念）"""
    await _require_mpt_ready()
    async with client:
        result = await client.analyze_reference_video(request.url)
    return ReferenceVideoResponse(**result)


@router.post("/hevi/submit-job", response_model=GenerateVideoResponse)
async def submit_job_from_hevi(
    production_id: str = Query(...),
    revision_id: str = Query(...),
    topic: str = Query(...),
    video_count: int = Query(1, ge=1, le=10),
    aspect: str = Query("9:16"),
    voice: str = Query("zh-CN-XiaoxiaoNeural"),
) -> GenerateVideoResponse:
    """从 hevi 工作流提交 MPT 任务（内部调用）"""
    await _require_mpt_ready()
    task_id = await submit_mpt_job_from_hevi(
        production_id=production_id,
        revision_id=revision_id,
        topic=topic,
        video_count=video_count,
        aspect=aspect,
        voice=voice,
    )
    return GenerateVideoResponse(
        task_id=task_id,
        status="submitted",
        message="Hevi workflow submitted to MPT",
    )


@router.get("/health")
async def health_check() -> dict[str, Any]:
    """MPT 集成健康检查，同时验证实际 MPT API。"""
    provider_status = await probe_provider("mpt", timeout_s=3.0)
    return {
        "status": "ok" if provider_status["ready"] else "degraded",
        "service": "mpt-integration",
        "provider": provider_status,
    }
