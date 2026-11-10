"""制片厂 API —— 工具箱 / 产线 / 工单。"""

from __future__ import annotations

import base64
import contextlib
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
from hevi.studio import craft_ledger, craft_s22, format_events, generalist_s23
from hevi.studio.assets import list_assets
from hevi.studio.conversational_edit import execute_edit
from hevi.studio.formats import (
    MATERIAL_FORMAT_ID,
    gate_open,
    list_formats,
    resolve_format,
)
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
    # S21：用户入口先选“出品形式”；旧调用方仍可只传 line_id。
    line_id: str | None = None
    format: str | None = None
    style: str | None = None
    slots: dict[str, Any] = Field(default_factory=dict)
    slate_id: str | None = None
    execute: bool = False


class FormatEventRequest(BaseModel):
    event: str
    format: str = ""
    style: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)


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


@router.get("/formats")
async def get_studio_formats(
    has_media: bool = False,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """首页“出品形式”卡片。内部 line id 不出现，只给形式与子风格。"""
    from hevi.auth.dependencies import can_view_internal_lines

    admin = can_view_internal_lines(_user)
    items = list_formats(admin=admin, has_media=has_media)
    return {
        "formats": items,
        "total": len(items),
        "ai_drama_gate": {"open": gate_open("ai_drama")[0], "reason": gate_open("ai_drama")[1]},
    }


class FormatPlanRequest(BaseModel):
    format: str | None = None
    style: str | None = None
    line_id: str | None = None
    topic: str = ""
    slots: dict[str, Any] = Field(default_factory=dict)
    # S22：事实出处、跳过闸门、栏目模板；都不传时按默认生成。
    facts: list[dict[str, Any]] = Field(default_factory=list)
    skip_gates: list[str] = Field(default_factory=list)
    brief: dict[str, Any] | None = None
    series_template: str | None = None


_FORMAT_STYLE_PROMPTS = {
    "history_scene": "historical documentary still, period-accurate costume and architecture, cinematic light",
    "digital_human": "clean presenter portrait, soft studio light, chest-up framing",
    "live_drama": "photorealistic cinematic still, natural skin, shallow depth of field",
    "comic_drama": "anime key visual, clean line art, cel shading",
    "animation": "stylized 2D animation keyframe, clear silhouette",
    "explainer": "minimal editorial illustration, bold shapes, generous negative space",
    MATERIAL_FORMAT_ID: "documentary b-roll still, natural texture",
}


@router.post("/formats/plan")
async def plan_format(
    req: FormatPlanRequest,
    user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """选形式后先在画布出脚本 + 分镜（文字/关键帧提示），确认后再渲染。"""
    from hevi.auth.dependencies import can_view_internal_lines

    admin = can_view_internal_lines(user)
    try:
        plan = resolve_format(
            format_id=req.format,
            style_id=req.style,
            line_id=req.line_id,
            slots={**req.slots, "topic": req.topic or req.slots.get("topic") or ""},
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if plan["gated"] and not admin and not gate_open("ai_drama")[0]:
        raise HTTPException(
            status_code=403,
            detail=f"该出品形式即将开放：{gate_open('ai_drama')[1]}",
        )
    topic = str(req.topic or plan["slots"].get("topic") or "").strip()
    if not topic:
        raise HTTPException(status_code=422, detail="请先写一句主题或梗概")

    lines: list[str] = []
    title = topic[:40]
    try:
        from hevi.studio.tools import invoke_tool

        result = await invoke_tool("script.quick", {"topic": topic, "max_lines": 6})
        payload = result.payload or {}
        raw_lines = payload.get("script_lines") or []
        if isinstance(raw_lines, list):
            lines = [str(item.get("text") if isinstance(item, dict) else item) for item in raw_lines if item]
        title = str(payload.get("title") or title)
    except Exception:
        lines = []
    if not lines:
        parts = [part.strip() for part in topic.replace("。", "\n").replace("，", "\n").splitlines() if part.strip()]
        lines = (parts or [topic])[:6]

    style_key = str(plan.get("style") or "")
    style_prompt = _FORMAT_STYLE_PROMPTS.get(str(plan.get("format") or ""), "cinematic still")
    if str(plan.get("format") or "") == "comic_drama" and style_key == "light":
        style_prompt = "static comic panel, halftone texture, speech bubbles reserved"
    shots = [
        {
            "index": i + 1,
            "label": f"镜头 {i + 1}",
            "line": line,
            "keyframe_prompt": f"{style_prompt}. {line}",
            "duration_s": 5,
        }
        for i, line in enumerate(lines[:6])
    ]
    craft_plan = craft_s22.build_craft_plan(
        format_id=str(plan["format"]),
        style_id=style_key,
        topic=topic,
        lines=lines,
        shots=shots,
        slots={**plan.get("slots", {}), **req.slots},
        facts=req.facts,
        skip_gates=req.skip_gates,
        brief=req.brief,
        series_template_id=req.series_template,
    )
    with contextlib.suppress(Exception):
        # 账本写失败不该挡住出片计划；后台会少一行报价。
        craft_ledger.record_plan(craft_plan)
    generalist = generalist_s23.plan_for(
        str(plan["format"]),
        style_key,
        topic=topic,
        slots={**plan.get("slots", {}), **req.slots},
    )
    return {
        "format": plan["format"],
        "style": style_key,
        "line_id": plan["line_id"],
        "title": title,
        "script": {"title": title, "lines": lines},
        "shots": shots,
        "craft": craft_plan,
        "generalist": generalist,
        "requires_confirm": True,
    }


@router.post("/format-events")
async def record_format_event(
    req: FormatEventRequest,
    user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    try:
        format_events.record_event(
            req.event,
            user_id=str((user or {}).get("id") or ""),
            format_id=req.format,
            style=req.style,
            detail=req.detail,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/format-metrics")
async def get_format_metrics(
    user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """管理后台：形式选择、自动被改选、分镜修改、完成率。"""
    from hevi.auth.dependencies import can_view_internal_lines

    if not can_view_internal_lines(user):
        raise HTTPException(status_code=403, detail="仅管理员可查看形式埋点")
    return format_events.metrics()


class CraftPlanRequest(BaseModel):
    format: str = "explainer"
    style: str = ""
    topic: str = ""
    lines: list[str] = Field(default_factory=list)
    shots: list[dict[str, Any]] = Field(default_factory=list)
    slots: dict[str, Any] = Field(default_factory=dict)
    facts: list[dict[str, Any]] = Field(default_factory=list)
    skip_gates: list[str] = Field(default_factory=list)
    brief: dict[str, Any] | None = None
    series_template: str | None = None


class CraftReviewRequest(BaseModel):
    target: str = "script"
    topic: str = ""
    lines: list[str] = Field(default_factory=list)
    shots: list[dict[str, Any]] = Field(default_factory=list)
    facts: list[dict[str, Any]] = Field(default_factory=list)
    skipped_gates: list[str] = Field(default_factory=list)
    qc: dict[str, Any] = Field(default_factory=dict)
    allow_llm: bool = False


class GeneralistPlanRequest(BaseModel):
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)


class CraftEventRequest(BaseModel):
    event: str
    plan_id: str = ""
    format: str = ""
    style: str = ""
    gate: str = ""
    route: str = ""
    model: str = ""
    seconds: float = 0
    cny: float = 0
    detail: dict[str, Any] = Field(default_factory=dict)


def _require_admin(user: dict[str, Any] | None) -> None:
    from hevi.auth.dependencies import can_view_internal_lines

    if not can_view_internal_lines(user):
        raise HTTPException(status_code=403, detail="仅管理员可查看")


@router.post("/craft/plan")
async def craft_plan(
    req: CraftPlanRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """S22：给任意脚本/分镜补镜头路线、报价、闸门、自检、声音与标题。"""
    lines = [str(line) for line in req.lines if str(line).strip()]
    if not lines and req.topic:
        lines = [req.topic]
    shots = req.shots or [
        {
            "index": i + 1,
            "line": line,
            "keyframe_prompt": line,
            "duration_s": 5,
        }
        for i, line in enumerate(lines)
    ]
    plan = craft_s22.build_craft_plan(
        format_id=req.format,
        style_id=req.style,
        topic=req.topic or (lines[0] if lines else ""),
        lines=lines,
        shots=shots,
        slots=req.slots,
        facts=req.facts,
        skip_gates=req.skip_gates,
        brief=req.brief,
        series_template_id=req.series_template,
    )
    with contextlib.suppress(Exception):
        craft_ledger.record_plan(plan)
    return plan


@router.post("/craft/review")
async def craft_review(
    req: CraftReviewRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """独立审稿：脚本或成片；只列问题。默认离线规则，不产生付费调用。"""
    if req.target == "film":
        return craft_s22.review_film_offline(req.qc)
    if req.target != "script":
        raise HTTPException(status_code=422, detail="target 只能是 script 或 film")
    return await craft_s22.review_script(
        topic=req.topic,
        lines=req.lines,
        shots=req.shots,
        facts=req.facts,
        skipped_gates=req.skipped_gates,
        allow_llm=req.allow_llm,
    )


@router.get("/craft/license-audit")
async def craft_license_audit(
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    return craft_s22.license_audit()


@router.get("/craft/ledger")
async def craft_cost_ledger(
    limit: int = 200,
    user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """管理后台：成本账本（时间 / 镜头 / 模型 / 秒数 / 金额）。"""
    _require_admin(user)
    return craft_ledger.summary(limit=max(1, min(limit, 2000)))


@router.post("/craft/events")
async def craft_event(
    req: CraftEventRequest,
    user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """闸门跳过/完成、渲染完成等事件写入同一本账。"""
    row = craft_ledger.record(
        {
            "kind": req.event or "event",
            "plan_id": req.plan_id,
            "format": req.format,
            "style": req.style,
            "shot": int(req.detail.get("shot") or 0),
            "route": req.route,
            "model": req.model,
            "seconds": req.seconds,
            "cny": req.cny,
            "status": str(req.detail.get("status") or "logged"),
            "note": f"gate={req.gate}" if req.gate else "",
            "user_id": str((user or {}).get("id") or ""),
        }
    )
    return {"ok": True, "row": row}


@router.get("/craft/series-templates")
async def craft_series_templates(
    format: str = "explainer",
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    items = craft_s22.series_templates(format)
    return {"templates": items, "total": len(items)}


@router.get("/generalist/catalog")
async def generalist_catalog(
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """S23：2D/3D 工作方法与自检能力清单。"""
    return generalist_s23.catalog()


@router.post("/generalist/plan")
async def generalist_plan(
    req: GeneralistPlanRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """S23：生成计划或跑一项自检；只做本地计算，不渲染、不付费。"""
    fn = generalist_s23.KINDS.get(req.kind)
    if fn is None:
        raise HTTPException(
            status_code=422,
            detail=f"unknown kind: {req.kind}; valid: {sorted(generalist_s23.KINDS)}",
        )
    try:
        return fn(**req.payload)
    except TypeError as exc:
        raise HTTPException(status_code=422, detail=f"payload mismatch: {exc}") from exc


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
    from hevi.auth.dependencies import can_view_internal_lines

    admin = can_view_internal_lines(user)
    try:
        plan = resolve_format(
            format_id=req.format,
            style_id=req.style,
            line_id=req.line_id,
            slots=req.slots,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    line_id = str(plan["line_id"])
    slots = dict(plan["slots"])
    # 质量门：门没开的 ai_drama 形式对普通用户显示“即将开放”，不报错。
    if plan["gated"] and not admin and not gate_open("ai_drama")[0]:
        raise HTTPException(
            status_code=403,
            detail=f"该出品形式即将开放：{gate_open('ai_drama')[1]}",
        )
    if launch_strict() and line_availability(line_id) != "ga" and not admin:
        if line_id == "ai_drama" and gate_open("ai_drama")[0]:
            pass
        else:
            raise HTTPException(
                status_code=403,
                detail="该出品形式即将开放，当前处于内测阶段",
            )
    fmt_id = str(plan.get("format") or "")
    style_id = str(plan.get("style") or "")
    if req.format:
        format_events.record_event(
            "format_selected",
            user_id=str(user["id"]),
            format_id=fmt_id if req.format != "auto" else "auto",
            style=style_id,
            detail={"auto_guess": slots.get("format_auto_guess")},
        )
    quota_job = ""
    quota = None
    if req.execute:
        quota = get_quota_service(await get_hevi_pg_pool())
        duration = requested_duration_seconds(
            duration_s=slots.get("duration_s") or slots.get("target_duration_s"),
            duration_archetype=str(slots.get("duration_archetype") or "") or None,
        )
        try:
            quota_job = await quota.reserve(
                str(user["id"]), kind="studio", duration_s=duration or 30
            )
        except QuotaError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc
    slate = Slate(
        line_id=line_id,
        slots=slots,
        slate_id=req.slate_id or "",
        execute=req.execute,
    )
    if req.execute:
        format_events.record_event(
            "render_started",
            user_id=str(user["id"]),
            format_id=fmt_id,
            style=style_id,
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
    if req.execute:
        format_events.record_event(
            "render_completed",
            user_id=str(user["id"]),
            format_id=fmt_id,
            style=style_id,
            detail={"status": result.status},
        )
    payload = result.to_dict()
    payload["format"] = fmt_id
    payload["style"] = style_id
    return payload


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


@router.get("/style-cards")
async def get_style_cards(
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """Built-in ai_drama style cards (cover + flat-light makeup reference).

    Images are inlined as data URLs so the picker works without a static mount.
    """
    from hevi.ai_drama.style_cards import list_style_cards

    cards = list_style_cards()
    for card in cards:
        for kind in ("cover", "makeup"):
            path = Path(str(card.get(f"{kind}_path") or ""))
            data_url = ""
            if path.is_file():
                encoded = base64.b64encode(path.read_bytes()).decode("ascii")
                data_url = f"data:image/jpeg;base64,{encoded}"
            card[f"{kind}_data_url"] = data_url
    return {"style_cards": cards, "total": len(cards)}


@router.get("/assets")
async def get_studio_assets(
    kind: str | None = None,
    line_id: str | None = None,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    items = [a.to_dict() for a in list_assets(kind=kind, line_id=line_id)]
    return {"assets": items, "total": len(items)}
