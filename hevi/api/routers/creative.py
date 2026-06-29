from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from oskill._schemas import Script, SubjectRef
from pydantic import BaseModel

from hevi.api.rate_limit import rate_limit
from hevi.auth.dependencies import get_current_user
from hevi.creative.assist_service import AssistService
from hevi.creative.workflow_service import WorkflowService

# Expensive GPU/LLM endpoints — require login AND throttle per-IP to bound
# resource-abuse cost. Auth applies to every route in this router.
router = APIRouter(
    prefix="/creative",
    tags=["creative"],
    dependencies=[
        Depends(get_current_user),
        Depends(rate_limit("creative", max_requests=30, window_s=60)),
    ],
)


# ── Request schemas ───────────────────────────────────────────────────────────


class ThreeViewRequest(BaseModel):
    character_description: str
    style: str = ""


class StoryboardRequest(BaseModel):
    script_text: str
    shots: int = 6


class StoryPredictRequest(BaseModel):
    reference_image: str
    direction: Literal["forward", "backward", "both"] = "forward"
    prediction_points: list[int] | None = None


class MultiAngleRequest(BaseModel):
    subject_description: str
    angles: list[str] | None = None


class TransitionRequest(BaseModel):
    first_frame: str
    last_frame: str
    duration_s: float
    video_provider: str = "wan22_local"
    output_path: str


class ElementEditRequest(BaseModel):
    elements: list[dict[str, Any]]
    operation: str
    target_index: int
    replacement: dict[str, Any] | None = None


class CharacterConsistencyRequest(BaseModel):
    portrait_image: str
    scene_descriptions: list[str]
    image_provider: str = "flux"
    output_dir: str


class StoryboardWorkflowRequest(BaseModel):
    script: dict[str, Any]
    subjects: list[dict[str, Any]] = []
    image_provider: str = "flux"
    output_dir: str
    grid_size: Literal[9, 25] | None = 9
    style: str | None = None
    lighting: str | None = None


class ComicToAnimationRequest(BaseModel):
    comic_image: str
    image_provider: str = "flux"
    video_provider: str = "wan22_local"
    output_path: str


# ── Dependencies ──────────────────────────────────────────────────────────────


async def get_assist_service() -> AssistService:
    return AssistService()


async def get_workflow_service() -> WorkflowService:
    return WorkflowService()


# ── Discovery ────────────────────────────────────────────────────────────────

_CAPABILITIES: list[dict[str, Any]] = [
    {"id": "three-view", "label": "三视图生成",
     "description": "角色正/侧/背三视图", "returns": "data"},
    {"id": "storyboard", "label": "分镜脚本",
     "description": "剧本→分镜", "returns": "data"},
    {"id": "story-predict", "label": "故事预测",
     "description": "参考帧推演剧情走向", "returns": "data"},
    {"id": "multi-angle", "label": "多角度描述",
     "description": "主体多机位 prompt", "returns": "prompt"},
    {"id": "transition", "label": "转场生成",
     "description": "首尾帧生成过渡视频", "returns": "media"},
    {"id": "element-edit", "label": "元素编辑",
     "description": "时间线元素批量操作", "returns": "data"},
    {"id": "workflow/character-consistency", "label": "角色一致性工作流", "returns": "media"},
    {"id": "workflow/storyboard", "label": "分镜工作流", "returns": "media"},
    {"id": "workflow/comic-to-animation", "label": "漫画转动画", "returns": "media"},
]


@router.get("/capabilities")
async def list_capabilities() -> list[dict[str, Any]]:
    return _CAPABILITIES


# ── oprim routes (6) ─────────────────────────────────────────────────────────


@router.post("/three-view")
async def gen_three_view(
    body: ThreeViewRequest,
    svc: Annotated[AssistService, Depends(get_assist_service)],
) -> dict[str, Any]:
    try:
        result = await svc.gen_three_view(
            character_description=body.character_description,
            style=body.style,
        )
        return result.model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/storyboard")
async def gen_storyboard(
    body: StoryboardRequest,
    svc: Annotated[AssistService, Depends(get_assist_service)],
) -> dict[str, Any]:
    try:
        result = await svc.gen_storyboard(
            script_text=body.script_text,
            shots=body.shots,
        )
        return result.model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/story-predict")
async def predict_story(
    body: StoryPredictRequest,
    svc: Annotated[AssistService, Depends(get_assist_service)],
) -> dict[str, Any]:
    result = await svc.predict_story(
        reference_image=Path(body.reference_image),
        direction=body.direction,
        prediction_points=body.prediction_points,
    )
    return result.model_dump()


@router.post("/multi-angle")
async def gen_multi_angle(
    body: MultiAngleRequest,
    svc: Annotated[AssistService, Depends(get_assist_service)],
) -> dict[str, Any]:
    try:
        result = await svc.gen_multi_angle(
            subject_description=body.subject_description,
            angles=body.angles,
        )
        return result.model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/transition")
async def make_transition(
    body: TransitionRequest,
    svc: Annotated[AssistService, Depends(get_assist_service)],
) -> dict[str, Any]:
    try:
        out = await svc.make_transition(
            first_frame=Path(body.first_frame),
            last_frame=Path(body.last_frame),
            duration_s=body.duration_s,
            video_provider=body.video_provider,
            output_path=Path(body.output_path),
        )
        return {"output_path": str(out)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/element-edit")
async def edit_video_element(
    body: ElementEditRequest,
    svc: Annotated[AssistService, Depends(get_assist_service)],
) -> list[dict[str, Any]]:
    try:
        return await svc.edit_video_elements(
            elements=body.elements,
            operation=body.operation,
            target_index=body.target_index,
            replacement=body.replacement,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ── oskill workflow routes (3) ────────────────────────────────────────────────


@router.post("/workflow/character-consistency")
async def run_character_consistency(
    body: CharacterConsistencyRequest,
    wf: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> dict[str, Any]:
    try:
        result = await wf.run_character_consistency(
            portrait_image=Path(body.portrait_image),
            scene_descriptions=body.scene_descriptions,
            image_provider=body.image_provider,
            output_dir=Path(body.output_dir),
        )
        return result.model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/workflow/storyboard")
async def run_storyboard_workflow(
    body: StoryboardWorkflowRequest,
    wf: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> dict[str, Any]:
    script = Script.model_validate(body.script)
    subjects = [SubjectRef.model_validate(s) for s in body.subjects]
    result = await wf.run_storyboard_workflow(
        script=script,
        subjects=subjects,
        image_provider=body.image_provider,
        output_dir=Path(body.output_dir),
        grid_size=body.grid_size,
        style=body.style,
        lighting=body.lighting,
    )
    return result.model_dump()


@router.post("/workflow/comic-to-animation")
async def run_comic_to_animation(
    body: ComicToAnimationRequest,
    wf: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> dict[str, Any]:
    out = await wf.run_comic_to_animation(
        comic_image=Path(body.comic_image),
        image_provider=body.image_provider,
        video_provider=body.video_provider,
        output_path=Path(body.output_path),
    )
    return {"output_path": str(out)}
