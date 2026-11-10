"""暖黑金图解 API：拆对标、逐拍自检、渲染任务、制作记忆、零件清单、10 秒模板。"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.explainer.warmgold import beats as beats_mod
from hevi.explainer.warmgold import memory as memory_mod
from hevi.explainer.warmgold import parts as parts_mod
from hevi.explainer.warmgold import reference as reference_mod
from hevi.explainer.warmgold import render as render_mod
from hevi.explainer.warmgold import scriptcheck, template

router = APIRouter(prefix="/explainer/warmgold", tags=["warmgold"])

JOB_ROOT = Path("data/warmgold_jobs")


class ReferenceRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    confirmed: bool = False


class CheckRequest(BaseModel):
    script: dict[str, Any]
    music_path: str | None = None
    beats: dict[str, Any] | None = None
    theme_color_id: str | None = None
    layout_id: str | None = None


class RenderRequest(BaseModel):
    script: dict[str, Any]
    music_path: str | None = None
    voice: bool = True
    fps: int = 24
    theme_color_id: str | None = None
    layout_id: str | None = None


class MemoryQuoteRequest(BaseModel):
    quote: str
    date: str | None = None


class MemoryRuleRequest(BaseModel):
    rule: str
    confirmed: bool = False


class TemplateRequest(BaseModel):
    sentence: str
    part_id: str = "random_walk"


def _job_dir(job_id: str) -> Path:
    safe = "".join(ch for ch in job_id if ch.isalnum() or ch in "-_")
    return JOB_ROOT / safe


def _write_status(job_id: str, payload: dict[str, Any]) -> None:
    target = _job_dir(job_id) / "status.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run_render_job(
    job_id: str, script: dict[str, Any], music_path: str | None, voice: bool, fps: int
) -> None:
    job = _job_dir(job_id)
    try:
        _write_status(job_id, {"status": "running", "job_id": job_id})
        report = render_mod.render(
            script,
            job / "warm_gold.mp4",
            workdir=job / "work",
            music_path=music_path,
            voice=voice,
            fps=fps,
        )
        _write_status(
            job_id,
            {
                "status": "done" if report.ok else "failed",
                "job_id": job_id,
                "out": report.out,
                "report": report.to_dict(),
            },
        )
    except Exception as exc:  # pragma: no cover - job boundary
        _write_status(job_id, {"status": "failed", "job_id": job_id, "error": str(exc)[:500]})


@router.post("/reference")
def reference_breakdown(
    req: ReferenceRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    if not req.payload:
        raise HTTPException(status_code=422, detail="payload is empty")
    if not req.payload.get("rights_declared"):
        raise HTTPException(status_code=422, detail="需要用户声明对参考视频/素材拥有权利")
    work = Path("data/warmgold_reference") / uuid.uuid4().hex[:12]
    report = reference_mod.decompose(req.payload, work)
    json_path, html_path = reference_mod.write_report(report, work)
    try:
        reference_mod.require_confirmation(report, req.confirmed)
        gate = "confirmed"
    except PermissionError as exc:
        gate = str(exc)
    return {
        "job_id": work.name,
        "gate": gate,
        "report": report,
        "json_path": str(json_path),
        "html_path": str(html_path),
        "owner": user.get("id") or user.get("email") or "",
    }


def _themed(script: dict[str, Any], theme_color_id: str | None, layout_id: str | None) -> dict[str, Any]:
    if not theme_color_id and not layout_id:
        return script
    from hevi.style_library.integrations import warmgold_script

    return warmgold_script(
        script,
        theme_color_id=theme_color_id or "C-27",
        layout_id=layout_id or "IG-003",
    )


@router.post("/check")
def check_script(
    req: CheckRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    script = _themed(req.script, req.theme_color_id, req.layout_id)
    try:
        beat_data = req.beats or beats_mod.build_beats(
            script, music_path=req.music_path or None
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = scriptcheck.check_script(script, beat_data, music_present=bool(req.music_path))
    result["beats"] = {
        "source": beat_data.get("source"),
        "bpm": beat_data.get("bpm"),
        "total_s": beat_data.get("total_s"),
        "count": len(beat_data.get("beats") or []),
    }
    return result


@router.post("/render", status_code=202)
def render_warm_gold(
    req: RenderRequest,
    background: BackgroundTasks,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    script = _themed(req.script, req.theme_color_id, req.layout_id)
    try:
        beat_data = beats_mod.build_beats(script, music_path=req.music_path or None)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    checks = scriptcheck.check_script(script, beat_data, music_present=bool(req.music_path))
    if not checks["pass"]:
        raise HTTPException(
            status_code=422, detail={"message": "脚本自检未通过", "issues": checks["issues"]}
        )
    job_id = uuid.uuid4().hex[:12]
    _job_dir(job_id).mkdir(parents=True, exist_ok=True)
    _write_status(
        job_id, {"status": "queued", "job_id": job_id, "owner": str(user.get("id") or "")}
    )
    background.add_task(_run_render_job, job_id, script, req.music_path, req.voice, req.fps)
    return {"job_id": job_id, "status": "queued", "checks": checks["metrics"]}


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str, user: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    target = _job_dir(job_id) / "status.json"
    if not target.is_file():
        raise HTTPException(status_code=404, detail="job not found")
    data: dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
    return data


@router.get("/parts")
def list_parts(user: Annotated[dict[str, Any], Depends(get_current_user)]) -> dict[str, Any]:
    return parts_mod.parts_manifest()


@router.post("/template10")
def template_10s(
    req: TemplateRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    try:
        script = template.build_10s(req.sentence, part_id=req.part_id)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    beat_data = beats_mod.build_beats(script)
    return {
        "script": script,
        "check": scriptcheck.check_script(script, beat_data, music_present=False),
    }


@router.get("/memory/{column}")
def get_memory(
    column: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    user_id = str(user.get("id") or user.get("email") or "anonymous")
    return {"user_id": user_id, "column": column, **memory_mod.list_memory(user_id, column)}


@router.post("/memory/{column}/quote")
def add_memory_quote(
    column: str,
    req: MemoryQuoteRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    user_id = str(user.get("id") or user.get("email") or "anonymous")
    try:
        return memory_mod.add_quote(user_id, column, req.quote, date=req.date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/memory/{column}/rule")
def add_memory_rule(
    column: str,
    req: MemoryRuleRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    user_id = str(user.get("id") or user.get("email") or "anonymous")
    return memory_mod.add_rule(user_id, column, req.rule, confirmed=req.confirmed)
