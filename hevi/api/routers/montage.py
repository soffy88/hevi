"""Executable OpenMontage-style production endpoints."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.montage import (
    AVAILABLE_PIPELINES,
    AgenticMontageConfig,
    agentic_montage_workflow,
    build_video_agent_plan,
    reflect_video_agent_plan,
    video_agent_transaction,
)
from hevi.studio.tools import list_tools

router = APIRouter(prefix="/montage", tags=["montage"])


class MontageRunRequest(BaseModel):
    pipeline: str = "animated-explainer"
    run_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,80}$")
    topic: str = ""
    source_text: str = ""
    transcript: str = ""
    script_lines: list[dict[str, Any]] = Field(default_factory=list)
    materials: list[dict[str, Any]] = Field(default_factory=list)
    media_path: str | None = None
    output_path: str | None = None
    aspect_ratio: str = "9:16"
    platforms: list[str] = Field(default_factory=list)
    render_runtime: str | None = None
    execute: bool = False
    auto_approve: bool = False
    approved_stages: list[str] = Field(default_factory=list)
    resume: bool = True
    budget_usd: float = Field(default=2.0, gt=0)


class VideoAgentRequest(BaseModel):
    requirement: str = Field(min_length=1)
    run_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,80}$")
    source_path: str | None = None
    media_path: str | None = None
    evidence_index_path: str | None = None
    transcript: str = ""
    script_lines: list[dict[str, Any]] = Field(default_factory=list)
    scenes: list[dict[str, Any] | str] = Field(default_factory=list)
    segments: list[dict[str, Any]] = Field(default_factory=list)
    question: str = ""
    aspect_ratio: str = "9:16"
    target_duration_s: float | None = Field(default=None, gt=0)
    segment_length_s: float = Field(default=10.0, gt=0)
    whisper_fallback: bool = False
    language: str | None = None
    execute: bool = False


@router.get("/pipelines")
async def pipelines(
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    return {"pipelines": [{"id": key, "description": value} for key, value in AVAILABLE_PIPELINES.items()]}


@router.post("/run")
async def run_montage(
    body: MontageRunRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    if body.pipeline not in AVAILABLE_PIPELINES:
        return {"status": "blocked", "errors": [f"unknown pipeline: {body.pipeline}"]}
    run_id = body.run_id or uuid.uuid4().hex
    output_dir = Path("output/montage/runs") / run_id
    return await agentic_montage_workflow(
        AgenticMontageConfig(
            pipeline=body.pipeline,
            budget_usd=body.budget_usd,
            execute=body.execute,
            auto_approve=body.auto_approve,
            resume=body.resume,
        ),
        {
            "topic": body.topic,
            "source_text": body.source_text,
            "transcript": body.transcript,
            "script_lines": body.script_lines,
            "materials": body.materials,
            "media_path": body.media_path,
            "output_path": body.output_path,
            "aspect_ratio": body.aspect_ratio,
            "platforms": body.platforms,
            "render_runtime": body.render_runtime,
            "run_id": output_dir.name,
            "approved_stages": body.approved_stages,
        },
        output_dir,
    )


@router.post("/video-agent/plan")
async def plan_video_agent(
    body: VideoAgentRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """VideoAgent 控制平面：规划和反思，不执行媒体副作用。"""

    available = {item.tool_id for item in list_tools()}
    plan = await build_video_agent_plan(
        body.requirement,
        input_data=body.model_dump(exclude_none=True),
        source_path=body.source_path or body.media_path or "",
        available_tools=available,
    )
    return {
        "status": "ok",
        "plan": plan.model_dump(mode="json"),
        "reflection": reflect_video_agent_plan(plan, available_tools=available),
    }


@router.post("/video-agent/run")
async def run_video_agent(
    body: VideoAgentRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """VideoAgent 事务：默认只规划；execute=true 才进入 HEVI 工具链。"""

    run_id = body.run_id or uuid.uuid4().hex
    output_dir = Path("output/montage/video-agent/runs") / run_id
    data = body.model_dump(exclude_none=True)
    data["output_dir"] = str(output_dir)
    data["available_tools"] = [item.tool_id for item in list_tools()]
    return await video_agent_transaction({"execute": body.execute}, data, output_dir)


__all__ = ["router"]
