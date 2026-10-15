"""Hevi StoryPlan API 路由（遵循能力契约与端点规范）。"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from hevi.storyplan.autofill import autofill_story_plan
from hevi.storyplan.check import run_story_check
from hevi.storyplan.take_select import select_best_take, TakeCandidate
from hevi.storyplan.export import export_storyboard_markdown, export_storyboard_html
from hevi.storyplan import capabilities


router = APIRouter(prefix="/story-plan", tags=["story-plan"])


class PlanRequest(BaseModel):
    topic: str = "小水滴去哪儿了"
    aspect: str = "16:9"
    fps: int = 30
    hook_type: str = "question"


class CheckRequest(BaseModel):
    plan: dict[str, Any] = Field(default_factory=dict)


class TakeSelectRequest(BaseModel):
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    acceptance_criteria: str = "验收点通过"


@router.post("/plan")
async def api_story_plan_generate(req: PlanRequest) -> dict[str, Any]:
    try:
        plan = autofill_story_plan(
            req.topic,
            aspect=req.aspect,
            fps=req.fps,
            hook_type=req.hook_type,
        )
        return {"status": "succeeded", "plan": plan.model_dump()}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


@router.post("/check")
async def api_story_plan_check(req: CheckRequest) -> dict[str, Any]:
    try:
        from hevi.storyplan.model import StoryPlan
        plan = StoryPlan(**req.plan)
        report = run_story_check(plan)
        return {"status": "succeeded", "report": report.model_dump()}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


@router.post("/take-select")
async def api_take_select(req: TakeSelectRequest) -> dict[str, Any]:
    try:
        cands = [TakeCandidate(**c) for c in req.candidates]
        best, all_res = select_best_take(cands, req.acceptance_criteria)
        return {
            "status": "succeeded",
            "best": best.model_dump(),
            "candidates": [r.model_dump() for r in all_res],
        }
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


@router.get("/capabilities")
async def api_story_plan_capabilities() -> dict[str, Any]:
    caps = capabilities.list_capabilities()
    return {
        "capabilities": [
            {
                "name": c.name,
                "kind": c.kind,
                "aspects": c.aspects,
                "description": c.description,
                "params_schema": c.params_schema,
            }
            for c in caps
        ]
    }
