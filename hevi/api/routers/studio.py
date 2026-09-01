"""制片厂 API —— 工具箱 / 产线 / 工单。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.studio.assets import list_assets
from hevi.studio.conversational_edit import execute_edit
from hevi.studio.recipes import get_recipe, list_recipes
from hevi.studio.slate import Slate, run_slate
from hevi.studio.timeline import (
    export_timeline,
    get_timeline,
    list_timelines,
    patch_clip,
    ripple,
    set_bgm,
    split_at,
    timeline_from_edit_plan,
    timeline_from_film,
)
from hevi.studio.tools import invoke_tool, list_tools

router = APIRouter(prefix="/studio", tags=["studio"])


class SlateRequest(BaseModel):
    line_id: str
    slots: dict[str, Any] = Field(default_factory=dict)
    slate_id: str | None = None
    execute: bool = False


class ToolInvokeRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


@router.get("/tools")
async def get_studio_tools(
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    tools = [t.to_dict() for t in list_tools()]
    return {"tools": tools, "total": len(tools)}


@router.post("/tools/{tool_id}")
async def invoke_studio_tool(
    tool_id: str,
    req: ToolInvokeRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    result = await invoke_tool(tool_id, req.payload)
    if result.status == "failed" and result.reason.startswith("unknown tool"):
        raise HTTPException(status_code=404, detail=result.reason)
    return result.to_dict()


@router.get("/lines")
async def get_studio_lines(
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    lines = [r.to_dict() for r in list_recipes()]
    return {"lines": lines, "total": len(lines)}


@router.get("/lines/{line_id}")
async def get_studio_line(
    line_id: str,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    rec = get_recipe(line_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"unknown line: {line_id}")
    return rec.to_dict()


@router.get("/motion/shot-cards")
async def get_shot_cards(
    category: str | None = None,
    search: str | None = None,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """Discover the complete normalized Shotcraft runtime catalogue."""

    from hevi.motion.recipe_card import build_shotcraft_library, card_index, card_runtime_spec

    library = build_shotcraft_library()
    needle = (search or "").strip().lower()
    cards = [
        card
        for card in library.values()
        if (not category or card.category == category)
        and (
            not needle
            or needle in card.name.lower()
            or needle in card.purpose.lower()
        )
    ]
    return {
        "cards": [card_runtime_spec(card) for card in cards],
        "total": len(cards),
        "index": card_index(library),
    }


@router.post("/slates")
async def create_slate(
    req: SlateRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    slate = Slate(
        line_id=req.line_id,
        slots=req.slots,
        slate_id=req.slate_id or "",
        execute=req.execute,
    )
    result = await run_slate(slate)
    if result.status == "failed" and result.reason.startswith("unknown line"):
        raise HTTPException(status_code=404, detail=result.reason)
    return result.to_dict()


class TimelineCreateRequest(BaseModel):
    title: str = "untitled"
    edit_plan: dict[str, Any] = Field(default_factory=dict)
    slate_id: str | None = None
    film: str | None = None
    duration_s: float | None = None
    project_id: str | None = None


class TimelinePatchRequest(BaseModel):
    project_id: str | None = None
    clip_id: str | None = None
    action: str | None = None
    label: str | None = None
    duration_s: float | None = None
    text: str | None = None
    speed: float | None = Field(default=None, ge=0.25, le=4.0)
    reverse: bool | None = None
    transition: str | None = None
    effect: str | None = None
    bgm: str | None = None
    split_at_s: float | None = None
    ripple: bool = False


class TimelineExportRequest(BaseModel):
    output_path: str = "output/nle/timeline.mp4"


class TimelineChatRequest(BaseModel):
    message: str = Field(min_length=1)
    preview: bool = False
    render: bool = False
    output_path: str | None = None


@router.get("/timelines")
async def get_timelines(
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    items = [t.to_dict() for t in list_timelines()]
    return {"timelines": items, "total": len(items)}


@router.post("/timelines")
async def create_timeline(
    req: TimelineCreateRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    if req.film:
        tl = timeline_from_film(req.film, duration_s=req.duration_s, title=req.title)
    else:
        tl = timeline_from_edit_plan(req.edit_plan, title=req.title)
    if req.project_id:
        from hevi.studio.nle_workspace import attach_timeline, get_project

        if get_project(req.project_id) is None:
            raise HTTPException(status_code=404, detail="unknown NLE project")
        attach_timeline(req.project_id, tl.timeline_id)
    return tl.to_dict()


@router.get("/timelines/{timeline_id}")
async def get_one_timeline(
    timeline_id: str,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    tl = get_timeline(timeline_id)
    if tl is None:
        raise HTTPException(status_code=404, detail="unknown timeline")
    return tl.to_dict()


@router.patch("/timelines/{timeline_id}")
async def patch_timeline(
    timeline_id: str,
    req: TimelinePatchRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    tl = get_timeline(timeline_id)
    if tl is None:
        raise HTTPException(status_code=404, detail="unknown timeline")
    if req.project_id:
        from hevi.studio.nle_workspace import record_revision

        record_revision(req.project_id, tl)
    if req.bgm is not None:
        set_bgm(timeline_id, req.bgm)
    if req.split_at_s is not None:
        split_at(timeline_id, req.split_at_s)
    if req.clip_id:
        patched = patch_clip(
            timeline_id,
            req.clip_id,
            action=req.action,
            label=req.label,
            duration_s=req.duration_s,
            text=req.text,
            speed=req.speed,
            reverse=req.reverse,
            transition=req.transition,
            effect=req.effect,
        )
        if patched is None:
            raise HTTPException(status_code=404, detail="unknown clip")
    if req.ripple:
        ripple(timeline_id)
    tl = get_timeline(timeline_id)
    if tl is None:
        raise HTTPException(status_code=404, detail="unknown timeline")
    return tl.to_dict()


class NLEProjectRequest(BaseModel):
    name: str = "untitled"
    timeline_id: str | None = None


@router.get("/nle/presets")
async def get_nle_presets(
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    from hevi.studio.nle_workspace import EFFECTS, TRANSITIONS

    return {
        "local_first": True,
        "transitions": list(TRANSITIONS),
        "effects": list(EFFECTS),
        "shortcuts": {"delete": "drop", "m": "mute", "k": "keep", "s": "split", "r": "ripple"},
    }


@router.get("/nle/projects")
async def get_nle_projects(
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    from hevi.studio.nle_workspace import list_projects

    items = [item.to_dict() for item in list_projects()]
    return {"projects": items, "total": len(items)}


@router.post("/nle/projects", status_code=201)
async def create_nle_project(
    body: NLEProjectRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    timeline = get_timeline(body.timeline_id) if body.timeline_id else None
    if body.timeline_id and timeline is None:
        raise HTTPException(status_code=404, detail="unknown timeline")
    from hevi.studio.nle_workspace import create_project

    return create_project(body.name, timeline).to_dict()


@router.post("/nle/projects/{project_id}/timelines/{timeline_id}")
async def attach_nle_timeline(
    project_id: str,
    timeline_id: str,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    if get_timeline(timeline_id) is None:
        raise HTTPException(status_code=404, detail="unknown timeline")
    from hevi.studio.nle_workspace import attach_timeline

    project = attach_timeline(project_id, timeline_id)
    if project is None:
        raise HTTPException(status_code=404, detail="unknown NLE project")
    return project.to_dict()


@router.get("/nle/projects/{project_id}/revisions")
async def get_nle_revisions(
    project_id: str,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    from hevi.studio.nle_workspace import get_project, revisions

    if get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="unknown NLE project")
    items = revisions(project_id)
    return {"project_id": project_id, "revisions": items, "total": len(items)}


@router.post("/timelines/{timeline_id}/export")
async def export_one_timeline(
    timeline_id: str,
    req: TimelineExportRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    from pathlib import Path

    result = export_timeline(timeline_id, Path(req.output_path))
    if result.get("reason") == "unknown timeline":
        raise HTTPException(status_code=404, detail="unknown timeline")
    return result


@router.post("/timelines/{timeline_id}/chat")
async def chat_edit_timeline(
    timeline_id: str,
    req: TimelineChatRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """FireRed-style natural-language timeline edit with preview/re-render."""

    try:
        return execute_edit(
            timeline_id,
            req.message,
            preview=req.preview,
            render=req.render,
            output_path=req.output_path,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class DailyCalendarRequest(BaseModel):
    calendar_id: str
    name: str
    line_id: str
    platforms: list[str] = Field(default_factory=list)


class DailyTopicsRequest(BaseModel):
    topics: list[dict[str, Any]] = Field(default_factory=list)


class DailyTickRequest(BaseModel):
    calendar_id: str | None = None
    now: str | None = None
    publish: bool = True


class VeyaProduceRequest(BaseModel):
    line_id: str
    slots: dict[str, Any] = Field(default_factory=dict)
    render_runtime: str | None = None
    execute: bool = False
    publish: bool = False
    platforms: list[str] = Field(default_factory=list)


@router.get("/daily/calendars")
async def get_daily_calendars(
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    from hevi.studio.daily import list_calendars

    items = [c.to_dict() for c in list_calendars()]
    return {"calendars": items, "total": len(items)}


@router.post("/daily/calendars")
async def post_daily_calendar(
    req: DailyCalendarRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    from hevi.studio.daily import upsert_calendar

    try:
        cal = upsert_calendar(
            calendar_id=req.calendar_id,
            name=req.name,
            line_id=req.line_id,
            platforms=req.platforms,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return cal.to_dict()


@router.post("/daily/calendars/{calendar_id}/topics")
async def post_daily_topics(
    calendar_id: str,
    req: DailyTopicsRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    from hevi.studio.daily import add_topics

    try:
        cal = add_topics(calendar_id, req.topics)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="unknown calendar") from exc
    return cal.to_dict()


@router.post("/daily/tick")
async def post_daily_tick(
    req: DailyTickRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    from hevi.studio.daily import tick

    jobs = await tick(now=req.now, calendar_id=req.calendar_id, publish=req.publish)
    return {"jobs": [j.to_dict() for j in jobs], "count": len(jobs)}


@router.get("/daily/jobs")
async def get_daily_jobs(
    calendar_id: str | None = None,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    from hevi.studio.daily import list_jobs

    items = [j.to_dict() for j in list_jobs(calendar_id=calendar_id)]
    return {"jobs": items, "total": len(items)}


@router.get("/veya/capabilities")
async def get_veya_capabilities(
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    from hevi.studio.veya import list_capabilities

    return list_capabilities()


@router.post("/veya/produce")
async def post_veya_produce(
    req: VeyaProduceRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    from hevi.studio.veya import produce

    job = await produce(
        line_id=req.line_id,
        slots=req.slots,
        render_runtime=req.render_runtime,
        execute=req.execute,
        publish=req.publish,
        platforms=req.platforms,
    )
    return job.to_dict()


@router.get("/veya/jobs/{job_id}")
async def get_veya_job(
    job_id: str,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    from hevi.studio.veya import get_job

    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown job")
    return job.to_dict()


class AssetPullRequest(BaseModel):
    pack: str = "celebrities30s"
    force: bool = False
    root: str | None = None


@router.get("/packs")
async def get_studio_packs(
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    from hevi.studio.packs import list_packs

    packs = list_packs()
    return {
        "packs": [
            {"id": key, "kind": val.get("kind"), "summary": val.get("summary")}
            for key, val in packs.items()
        ],
        "total": len(packs),
    }


@router.get("/voices")
async def get_studio_voices(
    language: str | None = None,
    local_only: bool = False,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    from hevi.studio.voices import list_voices

    voices = list_voices(language=language, local_only=local_only)
    return {"voices": [item.to_dict() for item in voices], "total": len(voices)}


@router.post("/assets/pull")
async def pull_studio_assets(
    req: AssetPullRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    from hevi.studio.packs import pull_pack

    try:
        result = pull_pack(req.pack, root=req.root, force=req.force)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"pull failed: {exc}") from exc
    return result.to_dict()


@router.get("/assets")
async def get_studio_assets(
    kind: str | None = None,
    line_id: str | None = None,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    items = [a.to_dict() for a in list_assets(kind=kind, line_id=line_id)]
    return {"assets": items, "total": len(items)}
