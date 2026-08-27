"""MoneyPrinterTurbo 集成路由 - hevi 暴露的 MPT 能力端点

hevi 作为编排中枢，代理调用 MPT 服务（素材/生成/发布/参考视频分析）。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from hevi.services.mpt_integration import MPTClient, submit_mpt_job_from_hevi

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


@router.post("/generate", response_model=GenerateVideoResponse)
async def generate_video(
    request: GenerateVideoRequest,
    client: MPTClientDependency,
) -> GenerateVideoResponse:
    """提交视频生成任务到 MPT"""
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
async def health_check() -> dict[str, str]:
    """MPT 服务健康检查"""
    return {"status": "ok", "service": "mpt-integration"}
