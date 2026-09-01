"""Standalone short-drama screenwriter API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.director.pipeline_schemas import Concept, Screenplay
from hevi.director.screenplay import generate_screenplay_draft
from hevi.shortdrama.screenwriter import review_screenplay, screenplay_markdown

router = APIRouter(prefix="/shortdrama/writer", tags=["shortdrama-writer"])


class WriterDraftRequest(BaseModel):
    title: str = "短剧单集"
    premise: str = Field(min_length=1, max_length=2000)
    raw_text: str = ""
    genre: str = ""
    tone: str = ""
    style: str = "电影感"
    target_audience: str = ""
    duration_archetype: str = "1-5min"
    mode: str = "adaptive"


class WriterReviewRequest(BaseModel):
    screenplay: dict[str, Any]


@router.get("/capabilities")
async def capabilities(_: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None) -> dict[str, Any]:
    return {
        "id": "ai-short-drama-screenwriter",
        "available": True,
        "scope": "script-only",
        "modes": ["adaptive", "literal", "staged"],
        "handoff": "storyboard/video-prompts",
        "does_not_generate": ["shot_list", "video_prompts", "media"],
    }


@router.post("/draft")
async def draft(
    body: WriterDraftRequest,
    _: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    material = body.raw_text.strip() or body.premise.strip()
    concept = Concept(
        theme=body.premise.strip(),
        tone=body.tone.strip(),
        style=body.style.strip(),
        target_audience=body.target_audience.strip(),
        duration_archetype=body.duration_archetype,
        quality_bar=body.genre.strip(),
    )
    try:
        screenplay = await generate_screenplay_draft(
            concept=concept,
            material_text=material,
            mode=body.mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "title": body.title,
        "scope": "script-only",
        "screenplay": screenplay.model_dump(mode="json"),
        "markdown": screenplay_markdown(screenplay, title=body.title),
        "review": review_screenplay(screenplay),
    }


@router.post("/review")
async def review(
    body: WriterReviewRequest,
    _: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    try:
        screenplay = Screenplay.model_validate(body.screenplay)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return review_screenplay(screenplay)
