"""Handraw-style library API (S27).

Read endpoints are public so the mobile selector paints without a session;
anything that writes files or changes a canvas requires the current user.
No endpoint calls a paid image model: covers and article illustrations are
composed locally with PIL, previews are hevi-authored SVG.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.style_library import ATTRIBUTION, catalog, consistency, integrations
from hevi.style_library import article as article_mod
from hevi.style_library import cover as cover_mod

router = APIRouter(prefix="/style-library", tags=["style-library"])
WORK_ROOT = Path("data/style_library")


class CoverRequest(BaseModel):
    source: Any = Field(default_factory=dict)
    style_id: str = "FA-039"
    theme_color_id: str = "C-27"
    layout_id: str = "SC-016"
    title: str = ""
    sizes: list[str] = Field(default_factory=lambda: ["9:16", "3:4", "16:9"])
    render: bool = False


class ArticleRequest(BaseModel):
    markdown: str
    style_id: str = "FA-001"
    theme_color_id: str = "C-05"
    points: int = 3
    title: str = ""
    render: bool = False


class DriftRequest(BaseModel):
    frames: list[str]
    reference: str | None = None
    threshold: float = consistency.DEFAULT_THRESHOLD
    seconds_per_frame: float | None = None
    semantic: bool = False


class LockRequest(BaseModel):
    style_id: str
    theme_color_id: str = "C-27"


class LayoutPlanRequest(BaseModel):
    stage: str
    style_id: str = "FA-001"
    theme_color_id: str = "C-27"
    subject: str = ""


class WarmGoldRequest(BaseModel):
    script: dict[str, Any]
    theme_color_id: str = "C-27"
    layout_id: str = "IG-003"


@router.get("/meta")
def meta() -> dict[str, Any]:
    return {**catalog.meta(), "attribution": ATTRIBUTION}


@router.get("/search")
def search(
    section: str = Query("styles", pattern="^(styles|layouts|colors|tones)$"),
    q: str = "",
    category: str = "",
    use_case: str = "",
    limit: int = Query(60, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    try:
        return catalog.search(
            section, query=q, category=category, use_case=use_case, limit=limit, offset=offset
        )
    except catalog.StyleLibraryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/recommend")
def recommend(topic: str = "", mood: str = "", platform: str = "", style_hint: str = "") -> dict[str, Any]:
    return catalog.recommend(topic, mood=mood, platform=platform, style_hint=style_hint)


@router.get("/selector", response_class=Response)
def selector() -> Response:
    return Response(catalog.selector_html(), media_type="text/html; charset=utf-8")


@router.get("/preview/{style_id}.svg", response_class=Response)
def preview(style_id: str) -> Response:
    try:
        svg = catalog.preview_svg(style_id)
    except catalog.StyleLibraryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(svg, media_type="image/svg+xml")


@router.get("/styles/{style_id}")
def style_detail(style_id: str) -> dict[str, Any]:
    try:
        style = catalog.get_style(style_id)
        return {
            "style": catalog.style_brief(style),
            "raw": style,
            "theme_suggestions": catalog.recommend(style.get("generation_name", ""))["theme_color"],
            "attribution": ATTRIBUTION,
        }
    except catalog.StyleLibraryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/layouts/{layout_id}")
def layout_detail(layout_id: str) -> dict[str, Any]:
    try:
        return {"layout": catalog.get_layout(layout_id), "attribution": ATTRIBUTION}
    except catalog.StyleLibraryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/colors/{color_id}")
def color_detail(color_id: str) -> dict[str, Any]:
    try:
        return {
            "color": catalog.get_color(color_id),
            "palette": catalog.theme_palette(color_id),
            "attribution": ATTRIBUTION,
        }
    except catalog.StyleLibraryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/palette/{color_id}")
def palette(color_id: str) -> dict[str, Any]:
    try:
        return catalog.theme_palette(color_id)
    except catalog.StyleLibraryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/lock")
def lock(req: LockRequest, user: Annotated[dict[str, Any], Depends(get_current_user)]) -> dict[str, Any]:
    try:
        return consistency.lock(req.style_id, req.theme_color_id)
    except catalog.StyleLibraryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/drift-check")
def drift_check(req: DriftRequest, user: Annotated[dict[str, Any], Depends(get_current_user)]) -> dict[str, Any]:
    report = consistency.check_frames(
        req.frames,
        reference=req.reference,
        threshold=req.threshold,
        seconds_per_frame=req.seconds_per_frame,
        semantic=req.semantic,
    )
    report["plan"] = consistency.plan_rerender(report)
    return report


@router.post("/layout-plan")
def layout_plan(req: LayoutPlanRequest) -> dict[str, Any]:
    return integrations.layout_plan(
        req.stage, style_id=req.style_id, theme_color_id=req.theme_color_id, subject=req.subject
    )


@router.post("/warmgold-script")
def warmgold_script(req: WarmGoldRequest) -> dict[str, Any]:
    try:
        return integrations.warmgold_script(
            req.script, theme_color_id=req.theme_color_id, layout_id=req.layout_id
        )
    except catalog.StyleLibraryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/cover/plan")
def cover_plan(req: CoverRequest) -> dict[str, Any]:
    try:
        return cover_mod.plan_cover(
            req.source,
            style_id=req.style_id,
            theme_color_id=req.theme_color_id,
            layout_id=req.layout_id,
            title=req.title,
        )
    except catalog.StyleLibraryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/cover/render")
def cover_render(req: CoverRequest, user: Annotated[dict[str, Any], Depends(get_current_user)]) -> dict[str, Any]:
    try:
        plan = cover_mod.plan_cover(
            req.source,
            style_id=req.style_id,
            theme_color_id=req.theme_color_id,
            layout_id=req.layout_id,
            title=req.title,
        )
        job = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
        out = WORK_ROOT / "covers" / job
        manifest = cover_mod.render_covers(plan, out, sizes=req.sizes)
        manifest["job"] = job
        manifest["relative"] = {
            size: str(Path(path).relative_to(WORK_ROOT)) for size, path in manifest["covers"].items()
        }
        return manifest
    except catalog.StyleLibraryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/article/plan")
def article_plan(req: ArticleRequest) -> dict[str, Any]:
    try:
        return article_mod.plan_article(
            req.markdown, style_id=req.style_id, theme_color_id=req.theme_color_id, points=req.points
        )
    except (ValueError, catalog.StyleLibraryError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/article/render")
def article_render(req: ArticleRequest, user: Annotated[dict[str, Any], Depends(get_current_user)]) -> dict[str, Any]:
    try:
        job = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
        out = WORK_ROOT / "articles" / job
        manifest = article_mod.export_article(
            req.markdown,
            out,
            style_id=req.style_id,
            theme_color_id=req.theme_color_id,
            points=req.points,
            title=req.title,
        )
        manifest["job"] = job
        return manifest
    except (ValueError, catalog.StyleLibraryError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/attribution.json")
def attribution_json() -> dict[str, Any]:
    return {
        "author": "yang0",
        "repository": "https://github.com/yang0/handraw-style",
        "license": "MIT License with Attribution Requirement",
        "text": ATTRIBUTION,
        "display": ["NOTICE", "关于 / 致谢页", "风格选择器页脚"],
    }
