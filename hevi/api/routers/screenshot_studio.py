"""Product screenshot compositor API."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.studio.screenshot_studio import (
    ANNOTATION_KINDS,
    FRAME_PRESETS,
    ScreenshotProject,
    animation_plan,
    get_project,
    list_projects,
    new_project,
    render_project,
    update_project,
)

router = APIRouter(prefix="/studio/screenshot", tags=["screenshot-studio"])


class ScreenshotCreateRequest(BaseModel):
    title: str = "untitled screenshot"
    screenshot_path: str = ""
    frame: str = "browser"
    width: int = Field(default=1600, ge=320, le=4096)
    height: int = Field(default=1000, ge=240, le=4096)
    background: str = "#eef2ff"


class ScreenshotPatchRequest(BaseModel):
    title: str | None = None
    frame: str | None = None
    width: int | None = Field(default=None, ge=320, le=4096)
    height: int | None = Field(default=None, ge=240, le=4096)
    background: str | None = None
    layers: list[dict[str, Any]] | None = None
    keyframes: list[dict[str, Any]] | None = None


class ScreenshotExportRequest(BaseModel):
    output_path: str = "output/screenshots/project.png"


def _require(project_id: str) -> ScreenshotProject:
    project = get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="unknown screenshot project")
    return project


@router.get("/presets")
async def presets(_: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None) -> dict[str, Any]:
    return {"frames": list(FRAME_PRESETS), "annotations": list(ANNOTATION_KINDS), "formats": ["png", "jpg", "svg-plan"]}


@router.get("/projects")
async def projects(_: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None) -> dict[str, Any]:
    items = [item.to_dict() for item in list_projects()]
    return {"projects": items, "total": len(items)}


@router.post("/projects", status_code=201)
async def create_project(
    body: ScreenshotCreateRequest,
    _: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    try:
        project = new_project(
            title=body.title,
            screenshot_path=body.screenshot_path,
            frame=body.frame,
            width=body.width,
            height=body.height,
            background=body.background,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return project.to_dict()


@router.get("/projects/{project_id}")
async def get_one_project(
    project_id: str,
    _: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    return _require(project_id).to_dict()


@router.patch("/projects/{project_id}")
async def patch_project(
    project_id: str,
    body: ScreenshotPatchRequest,
    _: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    if body.frame is not None and body.frame not in FRAME_PRESETS:
        raise HTTPException(status_code=422, detail=f"unknown frame: {body.frame}")
    patch = body.model_dump(exclude_unset=True)
    project = update_project(project_id, patch)
    if project is None:
        raise HTTPException(status_code=404, detail="unknown screenshot project")
    return project.to_dict()


@router.post("/projects/{project_id}/animation-plan")
async def get_animation_plan(
    project_id: str,
    _: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    return animation_plan(_require(project_id))


@router.post("/projects/{project_id}/export")
async def export_project(
    project_id: str,
    body: ScreenshotExportRequest,
    _: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    project = _require(project_id)
    output = Path(body.output_path)
    if output.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise HTTPException(status_code=422, detail="静态截图导出只支持 .png/.jpg/.jpeg")
    try:
        result = render_project(project, output)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result["missing_sources"]:
        raise HTTPException(status_code=422, detail={"code": "MISSING_SOURCE", **result})
    return result
