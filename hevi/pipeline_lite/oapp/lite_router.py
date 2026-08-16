"""oapp:lite_router —— Lite 完整闭环 HTTP 接入。

闭环:
  POST /lite/runs              选题 → LLM 出文案 → veya-loop 审稿 → awaiting_confirm
  GET  /lite/runs/{id}         查状态/文案/裁决(磁盘可恢复)
  GET  /lite/runs/{id}/preview.html  审稿 HTML 预览(不落 MP4)
  PATCH /lite/runs/{id}/script 人改文案(可选再跑 veya-loop)
  POST /lite/runs/{id}/reloop  对当前文案再跑一轮 veya-loop
  POST /lite/runs/{id}/confirm 确认 → 后台本地零费用出片
  POST /lite/assemble          兼容旧入口:直接给 cues 出片
  POST /lite/generate          同步出片(veya 外部编排直连)

run 状态落盘 data/lite_runs/{run_id}/run.json(重启可恢复)。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from hevi.core.workspace import new_task_id
from hevi.pipeline_lite.omodul.omodul_lite_assembler import run_lite_pipeline
from hevi.pipeline_lite.omodul.omodul_run_store import (
    load_run,
    save_run,
)
from hevi.pipeline_lite.omodul.omodul_run_store import (
    preview_html_path as store_preview_path,
)
from hevi.pipeline_lite.omodul.omodul_script_loop import (
    cues_from_script_text,
    run_veya_loop,
)
from hevi.pipeline_lite.oprim.oprim_html_gen import render_lite_html
from hevi.pipeline_lite.schemas import (
    LiteAssembleResult,
    LiteCue,
    LiteRunRecord,
    LiteTaskContext,
    ScriptDraft,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lite", tags=["lite"])

# 热缓存;权威源是磁盘。
_RUNS: dict[str, LiteRunRecord] = {}


# ── 请求/响应模型 ───────────────────────────────────────────────────────


class LiteAssembleRequest(BaseModel):
    """旧入口:直接提交 cues 出片。"""

    task_id: str = ""
    topic: str = Field(min_length=1, max_length=500)
    cues: list[LiteCue] = Field(default_factory=list)
    voice: str = "edge_tts_zh"
    width: int = 720
    height: int = 1280
    fps: int = 24
    output_name: str = "final.mp4"
    audio_path: str | None = None
    script: str = ""


class LiteAssembleAccepted(LiteAssembleResult):
    status: Literal["pending", "completed", "failed"] = "pending"


class LiteRunCreateRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    target_cues: int = Field(default=5, ge=3, le=10)
    max_rounds: int = Field(default=3, ge=1, le=5)
    width: int = 720
    height: int = 1280
    fps: int = 24
    script: str = ""
    cues: list[LiteCue] = Field(default_factory=list)


class LiteScriptPatch(BaseModel):
    title: str | None = None
    hook: str | None = None
    cues: list[LiteCue] | None = None
    script: str | None = None
    reloop: bool = False
    max_rounds: int = Field(default=2, ge=1, le=5)


class LiteConfirmRequest(BaseModel):
    cues: list[LiteCue] | None = None
    script: str | None = None


# ── 内部助手 ───────────────────────────────────────────────────────────


def _persist(rec: LiteRunRecord) -> LiteRunRecord:
    """写热缓存 + 磁盘。"""
    _RUNS[rec.run_id] = rec
    try:
        save_run(rec)
    except Exception as exc:
        logger.warning("lite run %s 落盘失败(热缓存仍可用): %s", rec.run_id, exc)
    return rec


def _get_run(run_id: str) -> LiteRunRecord:
    rec = _RUNS.get(run_id)
    if rec is not None:
        return rec
    loaded = load_run(run_id)
    if loaded is None:
        raise HTTPException(status_code=404, detail=f"run 不存在: {run_id}")
    _RUNS[run_id] = loaded
    return loaded


def _draft_from_input(
    topic: str,
    *,
    script: str = "",
    cues: list[LiteCue] | None = None,
    target_cues: int = 5,
) -> ScriptDraft | None:
    if cues:
        normalized = [
            c.model_copy(update={"index": i, "narration": c.narration.strip()})
            for i, c in enumerate(cues)
            if c.narration.strip()
        ]
        if normalized:
            return ScriptDraft(
                topic=topic,
                title=topic[:40],
                hook=normalized[0].narration,
                cues=normalized,
                target_cues=target_cues,
            )
    if script.strip():
        built = cues_from_script_text(topic, script)
        if built:
            return ScriptDraft(
                topic=topic,
                title=topic[:40],
                hook=built[0].narration,
                cues=built,
                target_cues=target_cues,
            )
    return None


def _write_preview(rec: LiteRunRecord) -> Path | None:
    """根据当前 draft 生成审稿 HTML(preview=True, 不落 MP4)。"""
    if rec.draft is None or not rec.draft.cues:
        return None
    out = store_preview_path(rec.run_id)
    render_lite_html(
        rec.draft.topic or rec.topic,
        rec.draft.cues,
        out,
        width=rec.width,
        height=rec.height,
        preview=True,
    )
    rec.preview_html_path = str(out)
    return out


async def _pipeline_from_cues(
    topic: str,
    cues: list[LiteCue],
    *,
    task_id: str | None = None,
    width: int = 720,
    height: int = 1280,
    fps: int = 24,
    audio_path: str | None = None,
) -> LiteAssembleResult:
    tid = task_id or new_task_id()
    ctx = LiteTaskContext(
        task_id=tid,
        topic=topic,
        cues=cues,
        width=width,
        height=height,
        fps=fps,
    )
    return await run_lite_pipeline(ctx, audio_path=audio_path)


async def _draft_and_review(run_id: str, body: LiteRunCreateRequest) -> None:
    rec = _get_run(run_id)
    rec.status = "drafting"
    rec.progress = 10
    _persist(rec)
    try:
        seed = _draft_from_input(
            body.topic,
            script=body.script,
            cues=body.cues,
            target_cues=body.target_cues,
        )
        rec.status = "reviewing"
        rec.progress = 30
        _persist(rec)
        loop = await run_veya_loop(
            body.topic,
            target_cues=body.target_cues,
            max_rounds=body.max_rounds,
            initial_draft=seed,
        )
        rec.draft = loop.draft
        rec.loop = loop
        rec.decision_trail = list(loop.decision_trail)
        _write_preview(rec)
        rec.status = "awaiting_confirm"
        rec.progress = 50
        if not loop.passed:
            rec.decision_trail.append(
                {
                    "stage": "awaiting_confirm",
                    "outcome": "degraded",
                    "note": "veya-loop 未满分通过,交人审确认",
                }
            )
        _persist(rec)
    except Exception as exc:
        logger.exception("lite run %s draft/review 失败", run_id)
        rec.status = "failed"
        rec.error = str(exc)[:2000]
        rec.progress = 0
        _persist(rec)


async def _render_run(run_id: str) -> None:
    rec = _get_run(run_id)
    if rec.draft is None or not rec.draft.cues:
        rec.status = "failed"
        rec.error = "无可用文案,无法出片"
        _persist(rec)
        return
    rec.status = "rendering"
    rec.progress = 60
    task_id = rec.task_id or new_task_id()
    rec.task_id = task_id
    _persist(rec)
    try:
        result = await _pipeline_from_cues(
            rec.topic,
            rec.draft.cues,
            task_id=task_id,
            width=rec.width,
            height=rec.height,
            fps=rec.fps,
        )
        rec.decision_trail.extend(result.decision_trail or [])
        if result.status == "completed" and result.video_path:
            rec.status = "completed"
            rec.video_path = str(result.video_path)
            rec.progress = 100
        else:
            rec.status = "failed"
            rec.error = result.error or "lite 装配失败"
            rec.progress = result.progress or 0
        _persist(rec)
    except Exception as exc:
        logger.exception("lite run %s render 失败", run_id)
        rec.status = "failed"
        rec.error = str(exc)[:2000]
        _persist(rec)


# ── 路由 ───────────────────────────────────────────────────────────────


@router.post("/runs", response_model=LiteRunRecord, status_code=202)
async def create_run(
    body: LiteRunCreateRequest,
    background_tasks: BackgroundTasks,
) -> LiteRunRecord:
    """选题 → 后台 LLM 出文案 + veya-loop → awaiting_confirm。"""
    run_id = new_task_id()
    rec = LiteRunRecord(
        run_id=run_id,
        status="drafting",
        topic=body.topic.strip(),
        width=body.width,
        height=body.height,
        fps=body.fps,
        progress=5,
        decision_trail=[{"stage": "accepted", "outcome": "queued"}],
    )
    _persist(rec)
    background_tasks.add_task(_draft_and_review, run_id, body.model_copy(deep=True))
    return rec


@router.get("/runs/{run_id}", response_model=LiteRunRecord)
async def get_run(run_id: str) -> LiteRunRecord:
    return _get_run(run_id)


@router.get("/runs/{run_id}/preview.html", response_model=None)
async def get_preview_html(run_id: str) -> FileResponse:
    """审稿 HTML 预览(不落 MP4)。无缓存 draft 时 404。"""
    rec = _get_run(run_id)
    path = Path(rec.preview_html_path) if rec.preview_html_path else store_preview_path(run_id)
    if not path.is_file():
        # 懒生成: 有 draft 则现写
        written = _write_preview(rec)
        if written is None:
            raise HTTPException(status_code=404, detail="尚无文案可预览")
        _persist(rec)
        path = written
    return FileResponse(
        path,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@router.patch("/runs/{run_id}/script", response_model=LiteRunRecord)
async def patch_script(run_id: str, body: LiteScriptPatch) -> LiteRunRecord:
    """人改文案;可选 reloop=true 再跑 veya-loop。"""
    rec = _get_run(run_id)
    if rec.status in ("drafting", "reviewing", "rendering"):
        raise HTTPException(status_code=409, detail=f"当前状态不可改稿: {rec.status}")
    if rec.draft is None:
        rec.draft = ScriptDraft(topic=rec.topic, cues=[])

    if body.script is not None:
        cues = cues_from_script_text(rec.topic, body.script)
        rec.draft = rec.draft.model_copy(
            update={
                "cues": cues,
                "hook": cues[0].narration if cues else rec.draft.hook,
            }
        )
    elif body.cues is not None:
        cues = [
            c.model_copy(update={"index": i})
            for i, c in enumerate(body.cues)
            if c.narration.strip()
        ]
        rec.draft = rec.draft.model_copy(
            update={
                "cues": cues,
                "hook": cues[0].narration if cues else rec.draft.hook,
            }
        )
    if body.title is not None:
        rec.draft = rec.draft.model_copy(update={"title": body.title.strip()[:80]})
    if body.hook is not None:
        rec.draft = rec.draft.model_copy(update={"hook": body.hook.strip()[:200]})

    if body.reloop:
        rec.status = "reviewing"
        _persist(rec)
        loop = await run_veya_loop(
            rec.topic,
            max_rounds=body.max_rounds,
            initial_draft=rec.draft,
        )
        rec.draft = loop.draft
        rec.loop = loop
        rec.decision_trail.extend(loop.decision_trail)
        rec.status = "awaiting_confirm"
        rec.progress = 50
        rec.error = None
    else:
        rec.status = "awaiting_confirm"
        rec.decision_trail.append({"stage": "manual_edit", "outcome": "ok"})

    _write_preview(rec)
    return _persist(rec)


@router.post("/runs/{run_id}/reloop", response_model=LiteRunRecord)
async def reloop(run_id: str, max_rounds: int = 2) -> LiteRunRecord:
    rec = _get_run(run_id)
    if rec.draft is None:
        raise HTTPException(status_code=422, detail="尚无文案可审")
    rec.status = "reviewing"
    _persist(rec)
    loop = await run_veya_loop(
        rec.topic,
        max_rounds=max(1, min(5, max_rounds)),
        initial_draft=rec.draft,
    )
    rec.draft = loop.draft
    rec.loop = loop
    rec.decision_trail.extend(loop.decision_trail)
    rec.status = "awaiting_confirm"
    rec.progress = 50
    rec.error = None
    _write_preview(rec)
    return _persist(rec)


@router.post("/runs/{run_id}/confirm", response_model=LiteRunRecord, status_code=202)
async def confirm_run(
    run_id: str,
    background_tasks: BackgroundTasks,
    body: LiteConfirmRequest | None = None,
) -> LiteRunRecord:
    """人确认文案 → 后台本地零费用渲染。"""
    rec = _get_run(run_id)
    if rec.status not in ("awaiting_confirm", "failed", "completed"):
        raise HTTPException(
            status_code=409,
            detail=f"当前状态不可确认出片: {rec.status}",
        )
    body = body or LiteConfirmRequest()
    if body.script or body.cues:
        seed = _draft_from_input(
            rec.topic,
            script=body.script or "",
            cues=body.cues,
            target_cues=len(body.cues or []) or 5,
        )
        if seed is not None:
            rec.draft = seed
            _write_preview(rec)
    if rec.draft is None or not rec.draft.cues:
        raise HTTPException(status_code=422, detail="文案为空,无法出片")
    rec.status = "rendering"
    rec.progress = 55
    rec.error = None
    rec.decision_trail.append({"stage": "confirmed", "outcome": "queued_render"})
    _persist(rec)
    background_tasks.add_task(_render_run, run_id)
    return rec


@router.post("/assemble", response_model=LiteAssembleAccepted, status_code=202)
async def assemble_lite(
    body: LiteAssembleRequest,
    background_tasks: BackgroundTasks,
) -> LiteAssembleAccepted:
    """兼容旧入口:直接 cues/script → 后台出片。"""
    if not body.task_id:
        body.task_id = new_task_id()
    cues = list(body.cues)
    if not cues and body.script.strip():
        cues = cues_from_script_text(body.topic, body.script)
    if not cues:
        raise HTTPException(status_code=422, detail="cues 不能为空(可传 script 按行拆分)")
    background_tasks.add_task(
        _run_background_assemble,
        body.topic,
        cues,
        body.task_id,
        body.width,
        body.height,
        body.fps,
        body.audio_path,
    )
    return LiteAssembleAccepted(
        task_id=body.task_id,
        status="pending",
        progress=0,
        decision_trail=[{"stage": "accepted", "outcome": "queued"}],
    )


@router.post("/generate", response_model=LiteAssembleResult, status_code=201)
async def generate_lite_sync(body: LiteAssembleRequest) -> LiteAssembleResult:
    """同步出片:veya/外部编排直连。"""
    if not body.task_id:
        body.task_id = new_task_id()
    cues = list(body.cues)
    if not cues and body.script.strip():
        cues = cues_from_script_text(body.topic, body.script)
    if not cues:
        cues = [
            LiteCue(
                index=0,
                narration=body.topic,
                props={"title": body.topic, "fullscreen": True},
            )
        ]
    try:
        return await _pipeline_from_cues(
            body.topic,
            cues,
            task_id=body.task_id,
            width=body.width,
            height=body.height,
            fps=body.fps,
            audio_path=body.audio_path,
        )
    except Exception as exc:
        logger.exception("lite %s 同步生成崩溃: %s", body.task_id, exc)
        return LiteAssembleResult(
            task_id=body.task_id,
            status="failed",
            error=f"lite pipeline raised: {exc}",
            decision_trail=[{"stage": "failed", "outcome": "exception"}],
        )


async def _run_background_assemble(
    topic: str,
    cues: list[LiteCue],
    task_id: str,
    width: int,
    height: int,
    fps: int,
    audio_path: str | None,
) -> None:
    try:
        result = await _pipeline_from_cues(
            topic,
            cues,
            task_id=task_id,
            width=width,
            height=height,
            fps=fps,
            audio_path=audio_path,
        )
        logger.info("lite %s done: %s", task_id, result.status)
    except Exception as exc:  # pragma: no cover
        logger.exception("lite %s 后台任务崩溃: %s", task_id, exc)


def _reset_runs_for_tests() -> None:
    """测试专用:清空内存 run 表(不删磁盘,由测试自行设 HEVI_LITE_RUNS_DIR)。"""
    _RUNS.clear()


__all__ = ["_RUNS", "LiteAssembleRequest", "_reset_runs_for_tests", "router"]
