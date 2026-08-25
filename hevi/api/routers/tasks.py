from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from obase.persistence import PgPool
from pydantic import BaseModel

from hevi.api.rate_limit import rate_limit
from hevi.artifact_store import ArtifactRepository
from hevi.artifact_store.http import artifact_delivery_url, materialize_artifact
from hevi.auth.dependencies import get_current_user
from hevi.auth.jwt_handler import decode_access_token
from hevi.core.config import settings
from hevi.credits.account_service import AccountService
from hevi.credits.billing_service import BillingService, InsufficientCredits
from hevi.credits.repository import CreditRepository
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.production.artifacts import ArtifactManifest, manifest_from_task
from hevi.production.contracts import ProductionRequest
from hevi.tasks.dispatch import schedule_local_compat
from hevi.tasks.progress import get_task_progress_stream
from hevi.tasks.repository import TaskRepository
from hevi.tasks.task_service import TaskService
from hevi.video import resolve_preset

router = APIRouter(prefix="/tasks", tags=["tasks"])


# ── Request schemas ───────────────────────────────────────────────────────────


class LongVideoRequest(BaseModel):
    topic: str
    duration_archetype: str
    # E3 execution preset (economy/balanced/fast). When set, fills provider/quality
    # defaults; any explicitly-set field below still overrides the preset.
    preset: str | None = None
    video_provider: str | None = None
    audio_provider: str | None = None
    num_characters: int = 1
    quality_profile: str | None = None
    style_preset: str | None = None
    # RFC-002 item 10: 暴露成片控制面 —— 转场风格 + 逐项镜头语言(风格/光照/
    # 运镜/调色)。这些过去仅 orchestrate_longvideo 内部支持,API 未暴露。
    transition: str = "fade"  # fade | cut | wipeleft | slideup ... (ffmpeg xfade)
    prompt_style: str | None = None
    prompt_lighting: str | None = None
    prompt_camera: str | None = None  # 运镜: "slow push in" / "pan left" ...
    prompt_color_grade: str | None = None
    avatar_portrait: str | None = None  # item 11: 数字人讲解肖像图(启用数字人 PiP)
    subject_id: str | None = None  # 角色库:选定角色 → 每镜头以其参考图 i2v 锁定身份


class EstimateRequest(BaseModel):
    duration_archetype: str
    video_provider: str = "ltx2_cloud"
    audio_provider: str = "edge_tts"
    num_characters: int = 1
    quality_profile: str = "standard"


# ── Dependencies ──────────────────────────────────────────────────────────────


async def get_pg_pool() -> PgPool:
    """Dependency to get the PostgreSQL pool."""
    return await get_hevi_pg_pool()


async def get_repository(pool: Annotated[PgPool, Depends(get_pg_pool)]) -> TaskRepository:
    """Dependency to get the task repository."""
    return TaskRepository(pool)


async def get_billing_service(
    pool: Annotated[PgPool, Depends(get_pg_pool)],
) -> BillingService:
    return BillingService(AccountService(CreditRepository(pool)))


async def get_task_service(
    repo: Annotated[TaskRepository, Depends(get_repository)],
    billing_svc: Annotated[BillingService, Depends(get_billing_service)],
) -> TaskService:
    return TaskService(repo, billing_svc)


# ── Serialization ────────────────────────────────────────────────────────────


def _serialize_task(t: dict[str, Any]) -> dict[str, Any]:
    return {**t, "task_id": str(t.get("id", "")), "percent": t.get("progress_pct", 0)}


def _serialize_shot(s: dict[str, Any]) -> dict[str, Any]:
    """剧集看板镜头卡片投影:从已落库的 shot_states 行取逐镜状态 + 一致性/诊断摘要。"""
    sel = s.get("selection_json") or {}
    out: dict[str, Any] = {
        "shot_index": s.get("shot_index"),
        "status": s.get("status"),
        "has_output": bool(s.get("output_path")),
        "consistency_score": sel.get("consistency_score"),
        "passed": sel.get("passed"),
        "diagnosis_category": sel.get("diagnosis_category"),
        "retry_count": sel.get("retry_count"),
    }
    prep = sel.get("preparation")
    if prep:
        out["preparation"] = prep
    return out


async def _load_task_manifest(
    task: dict[str, Any], repo: TaskRepository
) -> ArtifactManifest | None:
    """Read the DB artifact record first, then use the task projection."""
    config = task.get("config_json") or {}
    production_id = config.get("production_id")
    if production_id and isinstance(repo.pool, PgPool):
        manifest = await ArtifactRepository(repo.pool).get_manifest(str(production_id))
        if manifest is not None:
            return manifest
    return manifest_from_task(task)


# ── Routes ────────────────────────────────────────────────────────────────────


async def _create_task(
    body: LongVideoRequest,
    user: dict[str, Any],
    svc: TaskService,
    background_tasks: BackgroundTasks,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    try:
        # E3: expand preset → provider defaults; explicit fields still override.
        resolved = resolve_preset(
            body.preset,
            video_provider=body.video_provider,
            audio_provider=body.audio_provider,
            quality_profile=body.quality_profile,
        )
        # RFC-002 item 10: 控制参数全程透传进 config_json → orchestrate_longvideo。
        # 此前 quality_profile/style_preset 未传, 对生成无效 —— 一并修复。
        ctrl: dict[str, Any] = {
            "quality_profile": body.quality_profile or resolved.get("quality_profile", "standard"),
            "provider_quality_floor": int(resolved.get("provider_quality_floor", "9")),
            "transition": body.transition,
        }
        for k in (
            "style_preset",
            "prompt_style",
            "prompt_lighting",
            "prompt_camera",
            "prompt_color_grade",
            "avatar_portrait",
            "subject_id",
        ):
            v = getattr(body, k)
            if v is not None:
                ctrl[k] = v
        video_provider = resolved.get("video_provider", "ltx2_cloud")
        audio_provider = resolved.get("audio_provider", "edge_tts")
        # All unattended production enters through one contract. Keep the
        # direct call fallback for lightweight/unit-test service doubles.
        if isinstance(svc, TaskService):
            task = await svc.create_production(
                ProductionRequest(
                    source="automatic",
                    topic=body.topic,
                    duration_archetype=body.duration_archetype,
                    video_provider=video_provider,
                    audio_provider=audio_provider,
                    quality_profile=ctrl["quality_profile"],
                    num_characters=body.num_characters,
                    subject_ids=[body.subject_id] if body.subject_id else [],
                    options=ctrl,
                ),
                user_id=str(user["id"]),
                idempotency_key=idempotency_key,
            )
        else:
            task = await svc.create_task(
                topic=body.topic,
                duration_archetype=body.duration_archetype,
                video_provider=video_provider,
                audio_provider=audio_provider,
                user_id=str(user["id"]),
                idempotency_key=idempotency_key,
                num_characters=body.num_characters,
                **ctrl,
            )
        # Every PostgreSQL task is durable work. The API may submit it to the
        # queue, but the worker is the only production execution owner. The
        # compatibility helper below is restricted to non-PostgreSQL local
        # adapters and never runs billable work in FastAPI BackgroundTasks.
        task = await svc.submit_task(task["id"])

        if task["status"] != "queued":
            schedule_local_compat(background_tasks, svc, task["id"])

        return _serialize_task(task)
    except InsufficientCredits as exc:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "insufficient_credits",
                "credits_needed": exc.credits_needed,
                "credits_available": exc.credits_available,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/estimate")
async def estimate_task_credits(
    body: EstimateRequest,
    svc: Annotated[BillingService, Depends(get_billing_service)],
) -> dict[str, Any]:
    credits = await svc.estimate_credits(
        duration_archetype=body.duration_archetype,
        video_provider=body.video_provider,
        audio_provider=body.audio_provider,
        quality_profile=body.quality_profile,
        num_characters=body.num_characters,
    )
    return {"credits": credits, "credits_needed": credits}


@router.post(
    "",
    status_code=201,
    dependencies=[Depends(rate_limit("task_create", max_requests=20, window_s=60))],
)
async def create_task_alias(
    body: LongVideoRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[TaskService, Depends(get_task_service)],
    background_tasks: BackgroundTasks,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    return await _create_task(body, user, svc, background_tasks, idempotency_key)


@router.post(
    "/longvideo",
    status_code=201,
    deprecated=True,
    dependencies=[Depends(rate_limit("task_create", max_requests=20, window_s=60))],
)
async def create_longvideo_task(
    body: LongVideoRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[TaskService, Depends(get_task_service)],
    background_tasks: BackgroundTasks,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    """Compatibility alias for POST /api/tasks."""
    return await _create_task(body, user, svc, background_tasks, idempotency_key)


@router.get("")
async def list_tasks(
    repo: Annotated[TaskRepository, Depends(get_repository)],
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    status: Annotated[
        list[str] | None,
        Query(description="Filter by status (repeatable). E.g. ?status=queued&status=running"),
    ] = None,
) -> list[dict[str, Any]]:
    tasks = await repo.list_tasks(user_id=str(user["id"]), statuses=status)
    return [_serialize_task(t) for t in tasks]


@router.get("/{task_id}")
async def get_task_details(
    task_id: UUID,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[TaskRepository, Depends(get_repository)],
) -> dict[str, Any]:
    task = await repo.get_task(task_id)
    if not task or (task.get("user_id") and task["user_id"] != str(user["id"])):
        raise HTTPException(status_code=404, detail="Task not found")
    return _serialize_task(task)


@router.post("/{task_id}/resume")
async def resume_task(
    task_id: UUID,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[TaskService, Depends(get_task_service)],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    task = await svc.repository.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("user_id") and task["user_id"] != str(user["id"]):
        raise HTTPException(status_code=403, detail="Not your task")
    if task["status"] in ("completed", "running", "queued"):
        return _serialize_task(task)
    if isinstance(svc.repository.pool, PgPool):
        queued = await svc.enqueue_resume(task_id)
        return _serialize_task(queued)
    background_tasks.add_task(svc.resume_task, task_id)
    return _serialize_task(task)


class RegenerateRequest(BaseModel):
    """C3 verdict→定向返工请求体。hints 键为镜头 idx(JSON 字符串键会被 pydantic 转 int)。"""

    shot_ids: list[int]
    hints: dict[int, str] | None = None


@router.post("/{task_id}/regenerate")
async def regenerate_task_shots(
    task_id: UUID,
    body: RegenerateRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[TaskService, Depends(get_task_service)],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """C3 verdict→定向返工:后台重生成指定镜头(hints[idx] 并入 prompt),其余复用。"""
    task = await svc.repository.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("user_id") and task["user_id"] != str(user["id"]):
        raise HTTPException(status_code=403, detail="Not your task")
    if not body.shot_ids:
        raise HTTPException(status_code=400, detail="shot_ids must not be empty")
    if task["status"] != "completed":
        raise HTTPException(
            status_code=409, detail="task must be completed before regenerating shots"
        )
    # 重试次数硬上限(设计文档 §4.3):regenerate 是 fire-and-forget 后台任务,
    # TaskService.regenerate_task_shots 内部的 ValueError 不会传回这次 HTTP 请求——
    # 所以已到上限这件事要在这里同步查一遍,提前给调用方一个明确的 409,
    # 而不是让请求看似成功、实际后台悄悄丢弃。
    existing_shots = await svc.repository.get_shots(task_id)
    retry_by_index = {
        s["shot_index"]: int((s.get("selection_json") or {}).get("retry_count") or 0)
        for s in existing_shots
    }
    if all(retry_by_index.get(idx, 0) >= settings.shot_retry_max for idx in body.shot_ids):
        raise HTTPException(
            status_code=409,
            detail=f"all requested shots already at retry cap ({settings.shot_retry_max})",
        )

    # 3O 内化运行时接线:未显式给 hints 时,按 verdict 诊断分类自动推导(repair_agents)。
    # {shot_index: 修复指令} → omodul regenerate_shots 并入该镜头 prompt(一次一变量)。
    hints = body.hints
    if hints is None:
        from hevi.director.repair_agents import hints_from_failures

        hints = hints_from_failures(existing_shots, body.shot_ids)
    if isinstance(svc.repository.pool, PgPool):
        queued = await svc.enqueue_rework(
            task_id, shot_ids=body.shot_ids, hints=hints
        )
        return _serialize_task(queued)
    background_tasks.add_task(
        svc.regenerate_task_shots, task_id, shot_ids=body.shot_ids, hints=hints
    )
    return _serialize_task(task)


@router.get("/{task_id}/progress")
async def stream_task_progress(
    task_id: UUID,
    repo: Annotated[TaskRepository, Depends(get_repository)],
    token: Annotated[str | None, Query(description="JWT (SSE can't send headers)")] = None,
) -> StreamingResponse:
    """SSE endpoint for task progress tracking.

    EventSource cannot set Authorization headers, so the JWT is passed as a
    `?token=` query parameter and validated here (signed token → owner check).
    """
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        user_id = decode_access_token(token).get("sub")
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    task = await repo.get_task(task_id)
    if not task or (task.get("user_id") and task["user_id"] != str(user_id)):
        raise HTTPException(status_code=404, detail="Task not found")

    return StreamingResponse(
        get_task_progress_stream(task_id, repo), media_type="text/event-stream"
    )


async def _authorize_task_video(task_id: UUID, repo: TaskRepository, token: str | None) -> Path:
    """<video>/<img> 标签鉴权(不能带 Authorization 头,故 JWT 走 ?token=)+ 校验任务归属,
    返回该任务成片(final.mp4)的绝对路径。三个取片端点(video/cover/export)共用。
    """
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        user_id = decode_access_token(token).get("sub")
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    task = await repo.get_task(task_id)
    if not task or (task.get("user_id") and task["user_id"] != str(user_id)):
        raise HTTPException(status_code=404, detail="Task not found")

    manifest = await _load_task_manifest(task, repo)
    if manifest is not None:
        return await materialize_artifact(manifest, kind="video")
    if not settings.local_mode and not settings.debug:
        raise HTTPException(status_code=409, detail="Video artifact is not committed")
    path_str = task.get("result_video_path")
    if not path_str:
        raise HTTPException(status_code=409, detail="Video not ready")
    video_path = Path(path_str)
    if not video_path.is_absolute():
        video_path = (Path.cwd() / video_path).resolve()
    if not video_path.is_file():
        raise HTTPException(status_code=404, detail="Video file missing")
    return video_path


async def _authorize_task_audio(task_id: UUID, repo: TaskRepository, token: str | None) -> Path:
    """Return a verified audio artifact for a task owned by the token subject."""
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        user_id = decode_access_token(token).get("sub")
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    task = await repo.get_task(task_id)
    if not user_id or not task or (task.get("user_id") and task["user_id"] != str(user_id)):
        raise HTTPException(status_code=404, detail="Task not found")
    manifest = await _load_task_manifest(task, repo)
    if manifest is None:
        raise HTTPException(status_code=409, detail="Audio not ready")
    return await materialize_artifact(manifest, kind="audio")


@router.get("/{task_id}/video")
async def get_task_video(
    task_id: UUID,
    repo: Annotated[TaskRepository, Depends(get_repository)],
    token: Annotated[str | None, Query(description="JWT (<video> can't send headers)")] = None,
) -> FileResponse:
    """成片文件服务:返回该任务的 final.mp4。

    此前成片只落 result_video_path(容器本地路径),API 未暴露任何取片端点,前端
    "查看成片"无处可看。这里补上:同 progress 的 token 鉴权(<video src> 不能带
    Authorization 头,故 JWT 走 ?token=),校验任务归属,再回传 mp4(支持 Range,
    浏览器可拖动进度条)。
    """
    video_path = await _authorize_task_video(task_id, repo, token)
    return FileResponse(str(video_path), media_type="video/mp4", filename=f"{task_id}.mp4")


@router.get("/{task_id}/video-url")
async def get_task_video_url(
    task_id: UUID,
    repo: Annotated[TaskRepository, Depends(get_repository)],
    token: Annotated[str | None, Query(description="JWT")]=None,
) -> dict[str, Any]:
    """Return a short-lived signed URL for a committed video artifact.

    The authenticated API stream remains the local-mode fallback.  The
    production path points browsers directly at MinIO and avoids routing the
    full media payload through FastAPI.
    """

    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        user_id = decode_access_token(token).get("sub")
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    task = await repo.get_task(task_id)
    if not user_id or not task or (task.get("user_id") and task["user_id"] != str(user_id)):
        raise HTTPException(status_code=404, detail="Task not found")
    manifest = await _load_task_manifest(task, repo)
    if manifest is None:
        raise HTTPException(status_code=409, detail="Video artifact is not committed")
    expires_s = 300
    url = await artifact_delivery_url(manifest, kind="video", expires_s=expires_s)
    if url:
        return {"url": url, "expires_in": expires_s, "delivery": "signed_object_url"}
    return {
        "url": f"/api/tasks/{task_id}/video?token={quote(token, safe='')}",
        "expires_in": None,
        "delivery": "authenticated_api_stream",
    }


@router.get("/{task_id}/audio")
async def get_task_audio(
    task_id: UUID,
    repo: Annotated[TaskRepository, Depends(get_repository)],
    token: Annotated[str | None, Query(description="JWT (<audio> can't send headers)")] = None,
) -> FileResponse:
    """Serve a verified Voice Studio WAV artifact from ArtifactManifest."""
    audio_path = await _authorize_task_audio(task_id, repo, token)
    return FileResponse(str(audio_path), media_type="audio/wav", filename=f"{task_id}.wav")


@router.get("/{task_id}/cover")
async def get_task_cover(
    task_id: UUID,
    repo: Annotated[TaskRepository, Depends(get_repository)],
    token: Annotated[str | None, Query(description="JWT (<img> can't send headers)")] = None,
) -> FileResponse:
    """封面文件服务:装配器已在成片旁自动产出 <final>.cover.jpg(assembler.py extract_cover),
    此前从未通过 API 暴露过,前端无处可见。鉴权/归属校验同 /video。
    """
    video_path = await _authorize_task_video(task_id, repo, token)
    cover_path = video_path.with_suffix(".cover.jpg")
    if not cover_path.exists():
        raise HTTPException(status_code=404, detail="Cover not available")
    return FileResponse(str(cover_path), media_type="image/jpeg", filename=f"{task_id}.jpg")


@router.get("/{task_id}/export")
async def export_task_video(
    task_id: UUID,
    repo: Annotated[TaskRepository, Depends(get_repository)],
    token: Annotated[str | None, Query(description="JWT")] = None,
    format: Annotated[str, Query(description="mp4/mov/webm/gif")] = "mp4",
) -> FileResponse:
    """按格式导出成片:mp4 直传;mov 换封装(remux);webm/gif 真转码。产物缓存在成片旁,
    重复请求同格式不用重转。
    """
    from hevi.assembly.exporter import EXPORT_FORMATS, content_type_for, export_video

    if format not in EXPORT_FORMATS:
        raise HTTPException(status_code=400, detail=f"unsupported format, valid: {EXPORT_FORMATS}")

    video_path = await _authorize_task_video(task_id, repo, token)
    if format == "mp4":
        return FileResponse(str(video_path), media_type="video/mp4", filename=f"{task_id}.mp4")

    out_path = video_path.with_suffix(f".{format}")
    if not out_path.exists():
        try:
            await export_video(video_path, out_path, format)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"export failed: {exc}") from exc
    return FileResponse(
        str(out_path), media_type=content_type_for(format), filename=f"{task_id}.{format}"
    )


@router.get("/{task_id}/dub")
async def dub_task_video(
    task_id: UUID,
    repo: Annotated[TaskRepository, Depends(get_repository)],
    token: Annotated[str | None, Query(description="JWT")] = None,
    language: Annotated[str, Query(description="目标语种,如 en/ja/ko")] = "en",
) -> FileResponse:
    """翻译配音导出(§3 L2 护城河):ASR 转写 + 翻译 + 目标语种 TTS + mux 回成片。
    该模块此前只有核心逻辑(hevi.dub)而无 API 出口 —— 这里补上。首次请求现算
    (ASR+LLM+TTS+ffmpeg,较慢),产物缓存在成片旁,同语种重复请求直接回传。
    """
    from hevi.dub import dub_video

    video_path = await _authorize_task_video(task_id, repo, token)
    out_path = video_path.parent / f"{video_path.stem}.dub_{language}.mp4"
    if not out_path.exists():
        try:
            await dub_video(video_path=video_path, target_language=language, output_path=out_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"dub failed: {exc}") from exc
    return FileResponse(str(out_path), media_type="video/mp4", filename=f"{task_id}.{language}.mp4")


@router.get("/{task_id}/continuity-report")
async def get_continuity_report(
    task_id: UUID,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[TaskRepository, Depends(get_repository)],
) -> dict[str, Any]:
    """连续性报告(HEVI 路线图 Phase3 #41):从 shot_states(#27 扩展后的
    selection_json)派生的镜头清单 + 一致性/诊断明细 + Subject/StylePack 版本快照
    说明——纯聚合已落库数据,零增量计算成本。"""
    from hevi.tasks.continuity_report import build_continuity_report

    task = await repo.get_task(task_id)
    if not task or (task.get("user_id") and task["user_id"] != str(user["id"])):
        raise HTTPException(status_code=404, detail="Task not found")
    shots = await repo.get_shots(task_id)
    return build_continuity_report(shots)


@router.get("/{task_id}/shots")
async def list_task_shots(
    task_id: UUID,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[TaskRepository, Depends(get_repository)],
) -> list[dict[str, Any]]:
    """剧集看板镜头级视图:某任务的逐镜状态 + 一致性/诊断摘要(纯聚合 shot_states,零计算)。"""
    task = await repo.get_task(task_id)
    if not task or (task.get("user_id") and task["user_id"] != str(user["id"])):
        raise HTTPException(status_code=404, detail="Task not found")
    shots = await repo.get_shots(task_id)
    return [_serialize_shot(s) for s in shots]


# ── 镜头准备台(补 INC-001 §A/§G/§I/§L 缺失的候选确认工作流) ───────────────
# 参考 Jellyfish shot_preparation: shot.status pending→ready + 资产/对白候选
# accept/ignore + action_beats 三段 + 实体链接。状态挂在 selection_json.preparation。


@router.get("/{task_id}/shots/preparation")
async def get_shots_preparation(
    task_id: UUID,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[TaskRepository, Depends(get_repository)],
) -> dict[str, Any]:
    """镜头准备聚合状态:每镜的候选(资产/对白)+ 动作节拍 + pending 计数。

    未构建过准备状态的镜头用确定性提取现场生成(不落库,只读视图);
    已确认的镜头读回落库状态。
    """
    task = await repo.get_task(task_id)
    if not task or (task.get("user_id") and task["user_id"] != str(user["id"])):
        raise HTTPException(status_code=404, detail="Task not found")
    shots = await repo.get_shots(task_id)
    cfg = task.get("config_json") or {}
    episode_plan = cfg.get("episode_plan") or {}
    known_characters = [
        str(c.get("name") or "") for c in (episode_plan.get("characters_present") or [])
        if isinstance(c, dict) and c.get("name")
    ] or [str(c) for c in (episode_plan.get("characters") or []) if isinstance(c, str)]

    from hevi.season_planner.preparation import (
        build_shot_preparation,
        read_preparation,
    )

    views: list[dict[str, Any]] = []
    total_pending = 0
    for s in shots:
        prep = read_preparation(s)
        if prep is None:
            excerpt = str(
                (s.get("selection_json") or {}).get("script_excerpt")
                or (s.get("selection_json") or {}).get("shot_plan")
                or ""
            )
            prep = build_shot_preparation(
                script_excerpt=excerpt,
                known_characters=known_characters,
            )
        total_pending += prep.pending_count
        views.append(
            {
                "shot_index": s.get("shot_index"),
                "status": prep.status,
                "pending_count": prep.pending_count,
                "candidates": prep.candidates,
                "dialogue_candidates": prep.dialogue_candidates,
                "action_beats": prep.action_beats,
                "entity_links": prep.entity_links,
            }
        )
    # 生成前(shot_states 为空):集级候选视图 —— 从 episode_plan 的已知实体构建。
    if not views and episode_plan:
        from hevi.season_planner.preparation import extract_asset_candidates

        brief = str(episode_plan.get("title") or "")
        locations = [
            str(x) for x in (episode_plan.get("locations") or []) if x
        ]
        candidates = extract_asset_candidates(
            text=brief,
            known_characters=known_characters,
            known_scenes=locations,
        )
        views = [
            {
                "shot_index": -1,  # 集级(未拆镜)
                "status": "pending" if candidates else "ready",
                "pending_count": len(candidates),
                "candidates": candidates,
                "dialogue_candidates": [],
                "action_beats": {},
                "entity_links": [],
            }
        ]
        total_pending = len(candidates)
    return {
        "task_id": str(task_id),
        "shots": views,
        "total_pending": total_pending,
        "all_ready": all(v["status"] == "ready" for v in views) if views else True,
    }


class CandidateDecision(BaseModel):
    """候选确认:accept(收编)/ ignore(跳过)。scope: assets | dialogue。"""

    decision: Literal["accept", "ignore"] = "accept"
    scope: Literal["assets", "dialogue"] = "assets"


@router.patch("/{task_id}/shots/{shot_index}/candidates/{candidate_id}")
async def confirm_shot_candidate(
    task_id: UUID,
    shot_index: int,
    candidate_id: str,
    body: CandidateDecision,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[TaskRepository, Depends(get_repository)],
) -> dict[str, Any]:
    """确认一个镜头候选(accept/ignore)。全部处理完 → 镜头 ready。"""
    task = await repo.get_task(task_id)
    if not task or (task.get("user_id") and task["user_id"] != str(user["id"])):
        raise HTTPException(status_code=404, detail="Task not found")
    shots = await repo.get_shots(task_id)
    shot = next((s for s in shots if s["shot_index"] == shot_index), None)
    if shot is None:
        raise HTTPException(status_code=404, detail=f"shot {shot_index} not found")

    from hevi.season_planner.preparation import (
        build_shot_preparation,
        confirm_candidate,
        read_preparation,
        upsert_preparation,
    )

    prep = read_preparation(shot)
    if prep is None:
        prep = build_shot_preparation(
            script_excerpt=str(
                (shot.get("selection_json") or {}).get("script_excerpt") or ""
            )
        )
    confirm_candidate(
        prep, candidate_id=candidate_id, decision=body.decision, scope=body.scope
    )
    await repo.save_shot(upsert_preparation(shot, prep))
    return {
        "shot_index": shot_index,
        "status": prep.status,
        "pending_count": prep.pending_count,
        "entity_links": prep.entity_links,
    }


class ActionBeatsUpdate(BaseModel):
    """人工修正动作节拍三段(trigger/peak/aftermath)。"""

    trigger: str = ""
    peak: str = ""
    aftermath: str = ""


@router.patch("/{task_id}/shots/{shot_index}/action_beats")
async def update_shot_action_beats(
    task_id: UUID,
    shot_index: int,
    body: ActionBeatsUpdate,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[TaskRepository, Depends(get_repository)],
) -> dict[str, Any]:
    """人工修正一镜的动作节拍(确定性推断不理想时)。"""
    task = await repo.get_task(task_id)
    if not task or (task.get("user_id") and task["user_id"] != str(user["id"])):
        raise HTTPException(status_code=404, detail="Task not found")
    shots = await repo.get_shots(task_id)
    shot = next((s for s in shots if s["shot_index"] == shot_index), None)
    if shot is None:
        raise HTTPException(status_code=404, detail=f"shot {shot_index} not found")

    from hevi.season_planner.preparation import (
        read_preparation,
        upsert_preparation,
    )

    prep = read_preparation(shot)
    if prep is None:
        from hevi.season_planner.preparation import ShotPreparation

        prep = ShotPreparation()
    prep.action_beats = {
        "trigger": body.trigger,
        "peak": body.peak,
        "aftermath": body.aftermath,
    }
    await repo.save_shot(upsert_preparation(shot, prep))
    return {"shot_index": shot_index, "action_beats": prep.action_beats}


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: UUID,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[TaskRepository, Depends(get_repository)],
) -> dict[str, Any]:
    """取消任务(标记 cancelled;已完成/已取消的任务拒绝)。

    hevi 后台任务不支持强杀,取消语义 = 标记状态供 worker 检查后停止,
    与 Jellyfish GenerationTask 取消语义对齐(状态驱动)。
    """
    task = await repo.get_task(task_id)
    if not task or (task.get("user_id") and task["user_id"] != str(user["id"])):
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("status") in ("completed", "failed", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail=f"task already in terminal state: {task.get('status')}",
        )
    await repo.update_task(
        task_id,
        {
            "status": "cancelled",
            "error": "cancelled by user",
            "updated_at": datetime.now(UTC).replace(tzinfo=None),
        },
    )
    return {"task_id": str(task_id), "status": "cancelled"}


# ── Task 断点续跑(对标 DramaClaw Task Center) ──────────────────────────────

from hevi.tasks.checkpoint import build_checkpoint_from_task, resume_decision  # noqa: E402


@router.get("/{task_id}/checkpoint")
async def get_task_checkpoint(
    task_id: UUID,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[TaskRepository, Depends(get_repository)],
) -> dict[str, Any]:
    """断点查询: 任务的进度锚点(阶段/已完成镜头/百分比) + 续跑决策,
    前端据此展示"可续跑/跳过 N 镜"。确定性,不调 LLM。"""
    task = await repo.get_task(task_id)
    if not task or (task.get("user_id") and task["user_id"] != str(user["id"])):
        raise HTTPException(status_code=404, detail="Task not found")
    durable = await repo.latest_checkpoint(task_id)
    if durable is not None:
        progress = float(durable.get("progress_pct") or 0.0)
        attempt_status = str(durable.get("attempt_status") or "")
        resumable = attempt_status not in {"succeeded", "cancelled"} and progress < 100.0
        return {
            "task_id": str(task_id),
            "has_checkpoint": True,
            "resumable": resumable,
            "reason": (
                "latest durable checkpoint from the current/last attempt"
                if resumable
                else "attempt is terminal or already complete"
            ),
            "checkpoint_id": str(durable.get("id")),
            "attempt_id": str(durable.get("attempt_id")),
            "attempt_no": durable.get("attempt_no"),
            "attempt_status": attempt_status,
            "sequence": durable.get("sequence"),
            "stage": durable.get("stage"),
            "progress_pct": progress,
            "completed_shots": int(durable.get("completed_shots") or 0),
            "total_shots": int(durable.get("total_shots") or 0),
            "state": durable.get("state_json") or {},
            "artifact_manifest": durable.get("artifact_manifest_json"),
            "created_at": durable.get("created_at"),
        }
    cp = build_checkpoint_from_task(task)
    if cp is None:
        return {"task_id": str(task_id), "has_checkpoint": False}
    decision = resume_decision(task, cp)
    return {
        "task_id": str(task_id),
        "has_checkpoint": True,
        "resumable": decision["resumable"],
        "reason": decision["reason"],
        **cp.to_dict(),
    }
