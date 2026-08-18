"""制片厂 API —— 工具箱 / 产线 / 工单。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.studio.assets import list_assets
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


class TimelinePatchRequest(BaseModel):
    clip_id: str | None = None
    action: str | None = None
    label: str | None = None
    duration_s: float | None = None
    text: str | None = None
    bgm: str | None = None
    split_at_s: float | None = None
    ripple: bool = False


class TimelineExportRequest(BaseModel):
    output_path: str = "output/nle/timeline.mp4"


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
        return tl.to_dict()
    tl = timeline_from_edit_plan(req.edit_plan, title=req.title)
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
        )
        if patched is None:
            raise HTTPException(status_code=404, detail="unknown clip")
    if req.ripple:
        ripple(timeline_id)
    tl = get_timeline(timeline_id)
    if tl is None:
        raise HTTPException(status_code=404, detail="unknown timeline")
    return tl.to_dict()


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
