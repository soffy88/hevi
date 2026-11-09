"""制片厂 API —— 工具箱 / 产线 / 工单。"""

from __future__ import annotations

import mimetypes
import os
import uuid
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.auth.jwt_handler import decode_access_token
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.quota import QuotaError, get_quota_service, requested_duration_seconds
from hevi.studio.assets import list_assets
from hevi.studio.conversational_edit import execute_edit
from hevi.studio.recipes import get_recipe, launch_strict, line_availability, list_recipes
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


class VideoAnalyzeRequest(BaseModel):
    source_path: str = Field(min_length=1)
    semantic: bool = False


class VideoCompareRequest(BaseModel):
    source_path: str = Field(min_length=1)
    intent: dict[str, Any] = Field(default_factory=dict)


class VideoFeedbackRequest(BaseModel):
    finding_id: str = Field(min_length=1)
    severity: str = Field(min_length=1)
    layer: str = Field(min_length=1)
    target: str = Field(min_length=1)
    suggested_action: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)


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


@router.post("/video/analyze")
async def analyze_video(
    req: VideoAnalyzeRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """Thin HTTP adapter for the existing deterministic Video Intelligence service."""

    from hevi.video_intelligence.analysis import analyze_reel

    try:
        return analyze_reel(req.source_path, semantic=req.semantic).model_dump(mode="json")
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/video/compare")
async def compare_video(
    req: VideoCompareRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """Run the existing intent/artifact comparison without mutating upstream state."""

    from hevi.video_intelligence.analysis import analyze_reel
    from hevi.video_intelligence.comparison import compare_intent_to_artifact
    from hevi.video_intelligence.models import IntentProfile

    try:
        intent = IntentProfile.model_validate(req.intent)
        analysis = analyze_reel(req.source_path)
        return compare_intent_to_artifact(intent, analysis).model_dump(mode="json")
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/video/feedback")
async def create_video_feedback(
    req: VideoFeedbackRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """Create a proposal object only; this endpoint never mutates a project."""

    from hevi.video_intelligence.models import RevisionFeedback

    return RevisionFeedback(**req.model_dump()).model_dump(mode="json")


@router.get("/lines")
async def get_studio_lines(
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    from hevi.auth.dependencies import can_view_internal_lines

    lines = [r.to_dict() for r in list_recipes()]
    if not can_view_internal_lines(_user):
        lines = [line for line in lines if line.get("availability") != "internal"]
    return {"lines": lines, "total": len(lines)}


@router.get("/lines/{line_id}")
async def get_studio_line(
    line_id: str,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    rec = get_recipe(line_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"unknown line: {line_id}")
    from hevi.auth.dependencies import can_view_internal_lines

    payload = rec.to_dict()
    if payload.get("availability") == "internal" and not can_view_internal_lines(_user):
        raise HTTPException(status_code=404, detail=f"unknown line: {line_id}")
    return payload


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
        and (not needle or needle in card.name.lower() or needle in card.purpose.lower())
    ]
    return {
        "cards": [card_runtime_spec(card) for card in cards],
        "total": len(cards),
        "index": card_index(library),
    }


@router.post("/slates")
async def create_slate(
    req: SlateRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    if launch_strict() and line_availability(req.line_id) != "ga":
        raise HTTPException(
            status_code=403,
            detail=f"该产线（{req.line_id}）尚未开放，当前处于内测阶段",
        )
    quota_job = ""
    quota = None
    if req.execute:
        quota = get_quota_service(await get_hevi_pg_pool())
        duration = requested_duration_seconds(
            duration_s=req.slots.get("duration_s") or req.slots.get("target_duration_s"),
            duration_archetype=str(req.slots.get("duration_archetype") or "") or None,
        )
        try:
            quota_job = await quota.reserve(
                str(user["id"]), kind="studio", duration_s=duration or 30
            )
        except QuotaError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc
    slate = Slate(
        line_id=req.line_id,
        slots=req.slots,
        slate_id=req.slate_id or "",
        execute=req.execute,
    )
    try:
        result = await run_slate(slate)
    except Exception:
        if quota is not None:
            await quota.release(quota_job, reason="slate_exception")
        raise
    if result.status == "failed" and result.reason.startswith("unknown line"):
        if quota is not None:
            await quota.release(quota_job, reason="unknown_line")
        raise HTTPException(status_code=404, detail=result.reason)
    if quota is not None:
        if result.status == "completed" and result.data.get("result_video_path"):
            await quota.complete(quota_job)
        else:
            await quota.release(quota_job, reason=result.reason or result.status)
    return result.to_dict()


@router.post("/uploads")
async def upload_studio_source(
    file: Annotated[UploadFile, File(description="源视频（拆条/播客/译制用，≤200MB）")],
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Upload a source video for the source-media lines.

    Returns a container ``media_path`` that can be passed in a slate's slots
    (``media_path``) for shorts_clip / podcast_repurpose / localization_dub.
    """
    del user
    suffix = Path(file.filename or "source.mp4").suffix.lower()
    if suffix not in {".mp4", ".mov", ".webm", ".mkv", ".m4v"}:
        raise HTTPException(status_code=422, detail="只接受视频文件（mp4/mov/webm/mkv/m4v）")
    root = Path(os.environ.get("HEVI_OUTPUT_ROOT", "").strip() or (Path.cwd() / "output"))
    dest_dir = root / "uploads"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{uuid.uuid4().hex}{suffix}"
    limit = 200 * 1024 * 1024
    size = 0
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status_code=413, detail="源视频过大（上限 200MB）")
                out.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="空文件")
    return {"media_path": str(dest), "bytes": size}


_ARTIFACT_SUFFIXES = {
    ".mp4", ".mov", ".webm", ".m4a", ".wav", ".mp3", ".srt", ".ass",
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".json", ".txt",
    ".zip", ".fcpxml",
}


def _artifact_roots() -> list[Path]:
    roots = [
        os.environ.get("HEVI_OUTPUT_ROOT", ""),
        os.environ.get("HEVI_ASSET_ROOT", ""),
        str(Path.cwd() / "output"),
        str(Path.cwd() / "assets"),
        str(Path.cwd() / "data"),
    ]
    resolved: list[Path] = []
    for raw in roots:
        if not raw:
            continue
        try:
            path = Path(raw).expanduser().resolve()
        except OSError:
            continue
        if path.is_dir() and path not in resolved:
            resolved.append(path)
    return resolved


def _resolve_artifact(path: str) -> Path:
    """Resolve a produced artifact inside the deployment's output roots.

    Slate/canvas results expose absolute container paths.  Serving them needs a
    download endpoint, but never an arbitrary file read: the resolved target must
    stay under an allowed root and carry a media/document suffix.
    """
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = Path.cwd() / target
    try:
        resolved = target.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=404, detail="产物不存在或已被清理") from exc
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="产物不存在或已被清理")
    if resolved.suffix.lower() not in _ARTIFACT_SUFFIXES:
        raise HTTPException(status_code=415, detail="不支持的产物类型")
    roots = _artifact_roots()
    if not any(resolved == root or root in resolved.parents for root in roots):
        raise HTTPException(status_code=403, detail="产物不在允许的下载目录内")
    return resolved


_optional_bearer = HTTPBearer(auto_error=False)


@router.get("/artifacts/download")
async def download_studio_artifact(
    path: str = Query(min_length=1, description="slate/canvas 产物路径"),
    token: str | None = Query(default=None, description="JWT（<video> 无法带 Authorization 头）"),
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)] = None,
) -> FileResponse:
    """Authenticated download for slate / canvas artifacts.

    Accepts either an Authorization header (API clients) or a ``token`` query
    parameter (browser <a>/<video>), without the strict header dependency that
    would reject the query form before it is read.
    """
    raw = credentials.credentials if credentials is not None else token
    if not raw:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        payload = decode_access_token(raw)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    if not payload.get("sub"):
        raise HTTPException(status_code=401, detail="Invalid token: missing sub")
    resolved = _resolve_artifact(path)
    media_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    return FileResponse(
        str(resolved),
        media_type=media_type,
        filename=resolved.name,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(resolved.name)}"},
    )


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


class VeyaProduceRequest(BaseModel):
    line_id: str
    slots: dict[str, Any] = Field(default_factory=dict)
    render_runtime: str | None = None
    execute: bool = False
    platforms: list[str] = Field(default_factory=list)
    production_mode: str | None = None


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

    jobs = await tick(now=req.now, calendar_id=req.calendar_id)
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
        platforms=req.platforms,
        production_mode=req.production_mode,
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
