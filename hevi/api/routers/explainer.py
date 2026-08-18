"""Self-media explainer adapter.

The adapter owns only its E0-E2 planning state.  That state is persisted in
``automation_runs`` so a process restart never makes a submitted run invisible.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
)
from obase.persistence import PgPool
from pydantic import BaseModel

from hevi.auth.dependencies import get_current_user
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.explainer.contracts import (
    ExplainerAssembleRequest,
    ExplainerAssemblyAccepted,
    ExplainerCapabilityError,
    ExplainerResearchJob,
    ExplainerResearchRequest,
)
from hevi.explainer.props import deep_unpack_json
from hevi.explainer.research import research_and_generate, response_payload
from hevi.explainer.research_cache import (
    ensure_clean_session_id,
    load_research_cache,
    save_research_cache,
)
from hevi.presenters.repository import PresenterRepository
from hevi.production.execution import execution_binding
from hevi.runs.repository import AutomationRunRepository
from hevi.runs.task_projection import create_projection, update_projection
from hevi.subjects.reference_store import ReferenceStore
from hevi.tasks.repository import TaskRepository
from hevi.tasks.task_service import TaskService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/explainer", tags=["explainer"])
_KIND = "explainer"
_LAYER_ORDER = ["E0", "E1", "E2"]


class RunRequest(BaseModel):
    topic: str


class PresenterImageCheckRequest(BaseModel):
    image_url: str


class PresenterImageCheckResponse(BaseModel):
    valid: bool
    reason: str
    width: int | None = None
    height: int | None = None
    face_count: int | None = None
    face_ratio: float | None = None
    face_check: str = "skipped"


class LayerState(BaseModel):
    layer: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    gate_report: dict[str, Any] | None = None


class RunStatus(BaseModel):
    run_id: str
    status: str
    topic: str
    created_at: datetime
    completed_at: datetime | None = None
    current_layer: str | None = None
    layers: list[LayerState] = []
    result_portrait_path: str | None = None
    result_landscape_path: str | None = None
    error: str | None = None
    task_ids: list[str] = []
    mode: str = "legacy"
    artifact_manifest: dict[str, Any] | None = None
    decision_trail: list[dict[str, Any]] = []


async def get_run_repository(
    pool: Annotated[PgPool, Depends(get_hevi_pg_pool)],
) -> AutomationRunRepository:
    return AutomationRunRepository(pool)


async def _bind_explainer_presenter(
    body: ExplainerAssembleRequest,
    *,
    pool: PgPool,
    user_id: str,
) -> None:
    """Resolve a HEVI Presenter to a real provider strategy in-place."""
    presenter_repo = PresenterRepository(pool)
    requested_id = body.presenter_id or body.heygen_presenter_id
    row: dict[str, Any] | None = None
    if requested_id:
        try:
            uuid.UUID(requested_id)
        except ValueError:
            if body.presenter_id:
                raise HTTPException(
                    status_code=422, detail="presenter_id 格式无效"
                ) from None
            # Backward compatibility: old callers may still send a raw HeyGen
            # provider ID through heygen_presenter_id.
            body.presenter_provider = "heygen"
            body.presenter_name = "HeyGen 数字人"
            return
        row = await presenter_repo.get(requested_id, user_id)
        if row is None:
            raise HTTPException(status_code=404, detail="选择的数字人不存在")
    else:
        row = await presenter_repo.ensure_default(user_id)

    delivery = row.get("delivery_json") or {}
    configured_provider = str(delivery.get("provider") or "remotion").lower()
    external_id = delivery.get("heygen_presenter_id") or delivery.get(
        "provider_presenter_id"
    )
    body.presenter_id = str(row["id"])
    body.presenter_name = str(row.get("name") or "HEVI 数字人")
    if configured_provider == "heygen" and external_id:
        body.presenter_provider = "heygen"
        body.heygen_presenter_id = str(external_id)
    else:
        # Incomplete or absent external-provider configuration falls back to
        # HEVI's actual Remotion presenter, which always yields visible output.
        body.presenter_provider = "remotion"
        body.heygen_presenter_id = None


def _initial_layers() -> dict[str, dict[str, Any]]:
    return {
        layer: {
            "layer": layer,
            "status": "PENDING",
            "started_at": None,
            "finished_at": None,
            "error": None,
            "gate_report": None,
        }
        for layer in _LAYER_ORDER
    }


def _record_from_row(row: dict[str, Any]) -> dict[str, Any]:
    state = row.get("state_json") or {}
    return {
        "run_id": str(row["id"]),
        "user_id": row["user_id"],
        "status": row["status"],
        "topic": (row.get("input_json") or {}).get(
            "topic", (row.get("input_json") or {}).get("topic_or_url", "")
        ),
        "created_at": row["created_at"],
        "completed_at": row.get("completed_at"),
        "current_layer": state.get("current_layer"),
        "layers": state.get("layers") or _initial_layers(),
        "result_portrait_path": state.get("result_portrait_path"),
        "result_landscape_path": state.get("result_landscape_path"),
        "error": state.get("error"),
        "task_ids": [str(task_id) for task_id in (row.get("task_ids") or [])],
        "mode": state.get("mode", "legacy"),
        "artifact_manifest": state.get("artifact_manifest"),
        "decision_trail": state.get("decision_trail") or [],
    }


def _state_from_record(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "current_layer": rec.get("current_layer"),
        "layers": rec["layers"],
        "result_portrait_path": rec.get("result_portrait_path"),
        "result_landscape_path": rec.get("result_landscape_path"),
        "error": rec.get("error"),
        "mode": rec.get("mode", "legacy"),
        "artifact_manifest": rec.get("artifact_manifest"),
        "decision_trail": rec.get("decision_trail") or [],
    }


async def _save(repo: AutomationRunRepository, rec: dict[str, Any]) -> None:
    await repo.update(
        rec["run_id"],
        {
            "status": rec["status"],
            "state_json": _state_from_record(rec),
            "completed_at": rec.get("completed_at"),
            "task_ids": rec.get("task_ids") or [],
        },
    )


async def _get_owned_run(
    repo: AutomationRunRepository, run_id: str, user_id: str | None = None
) -> dict[str, Any]:
    try:
        row = await repo.get(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="run 不存在") from exc
    if (
        row is None
        or row.get("kind") != _KIND
        or (user_id is not None and row["user_id"] != user_id)
    ):
        raise HTTPException(status_code=404, detail="run 不存在")
    return _record_from_row(row)


async def _update_layer(
    repo: AutomationRunRepository, rec: dict[str, Any], layer: str, **kwargs: Any
) -> None:
    rec["layers"][layer].update(kwargs)
    rec["current_layer"] = layer
    await _save(repo, rec)


async def _finish_run(
    repo: AutomationRunRepository,
    rec: dict[str, Any],
    *,
    success: bool,
    portrait_path: str | None = None,
    landscape_path: str | None = None,
    error: str | None = None,
    artifact_manifest: dict[str, Any] | None = None,
    decision_trail: list[dict[str, Any]] | None = None,
) -> None:
    rec["status"] = "COMPLETED" if success else "FAILED"
    rec["completed_at"] = datetime.now(UTC).replace(tzinfo=None)
    rec["result_portrait_path"] = portrait_path
    rec["result_landscape_path"] = landscape_path
    if artifact_manifest is not None:
        rec["artifact_manifest"] = artifact_manifest
    if decision_trail is not None:
        rec["decision_trail"] = decision_trail
    if error:
        rec["error"] = error
    await _save(repo, rec)


async def _run_pipeline(repo: AutomationRunRepository, run_id: str) -> None:
    from hevi.explainer.production import render_narrated_storyboard
    from hevi.explainer.storyboard import gate_storyboard, generate_storyboard

    rec = await _get_owned_run(repo, run_id)
    task_repo = TaskRepository(repo.pool)
    task_id = (rec.get("task_ids") or [None])[0]

    async def set_task(**kwargs: Any) -> None:
        if task_id is not None:
            await update_projection(task_repo, task_id, **kwargs)

    rec["status"] = "RUNNING"
    await _save(repo, rec)
    await set_task(status="running", progress_pct=5.0)

    await _update_layer(repo, rec, "E0", status="RUNNING", started_at=datetime.now(UTC).isoformat())
    try:
        storyboard = await generate_storyboard(rec["topic"])
        await _update_layer(
            repo, rec, "E0", status="PASSED", finished_at=datetime.now(UTC).isoformat()
        )
        await set_task(status="running", progress_pct=35.0)
    except Exception as exc:
        await _update_layer(
            repo,
            rec,
            "E0",
            status="FAILED",
            error=str(exc)[:500],
            finished_at=datetime.now(UTC).isoformat(),
        )
        await _finish_run(repo, rec, success=False, error=f"E0 failed: {exc}")
        await set_task(status="failed", error=f"E0 failed: {exc}")
        return

    await _update_layer(repo, rec, "E1", status="RUNNING", started_at=datetime.now(UTC).isoformat())
    gate = gate_storyboard(storyboard)
    await _update_layer(
        repo,
        rec,
        "E1",
        status="PASSED" if gate.passed else "FAILED",
        finished_at=datetime.now(UTC).isoformat(),
        gate_report=gate.model_dump(),
    )
    if not gate.passed:
        await _finish_run(repo, rec, success=False, error=f"E1 gate failed: {gate.errors}")
        await set_task(status="failed", progress_pct=50.0, error=f"E1 gate failed: {gate.errors}")
        return
    await set_task(status="running", progress_pct=60.0)

    await _update_layer(repo, rec, "E2", status="RUNNING", started_at=datetime.now(UTC).isoformat())
    try:
        # 🚨 v9.1: 主管道同样走工单沙盒 data/workspace/{task_id}/。
        from hevi.core.workspace import WorkspaceManager

        ws = WorkspaceManager(task_id or run_id, pipeline_type="main_remotion")
        ws.update_progress("running", 60)
        result = await render_narrated_storyboard(storyboard, ws.root)
        ws.mark_step_done("render", progress=100)
        # v9.1 产物身份: 成片 SHA-256 绑定(竖屏主片), 返工/审核对同一稿。
        ws.record_result_sha(result.portrait_path)
        await _update_layer(
            repo, rec, "E2", status="PASSED", finished_at=datetime.now(UTC).isoformat()
        )
        await _finish_run(
            repo,
            rec,
            success=True,
            portrait_path=str(result.portrait_path),
            landscape_path=str(result.landscape_path),
        )
        await set_task(
            status="completed", progress_pct=100.0, result_video_path=str(result.portrait_path)
        )
    except Exception as exc:
        logger.exception("explainer run %s E2 failed", run_id)
        await _update_layer(
            repo,
            rec,
            "E2",
            status="FAILED",
            error=str(exc)[:500],
            finished_at=datetime.now(UTC).isoformat(),
        )
        await _finish_run(repo, rec, success=False, error=f"E2 failed: {exc}")
        await set_task(status="failed", error=f"E2 failed: {exc}")


async def _run_assembled_pipeline(repo: AutomationRunRepository, run_id: str) -> None:
    """Execute a human-approved v6 cue sheet through the shared task boundary."""
    from hevi.explainer.assembly import assemble_explainer_cues

    rec = await _get_owned_run(repo, run_id)
    task_repo = TaskRepository(repo.pool)
    task_id = (rec.get("task_ids") or [None])[0]
    # 隐患点 A 双保险:DB 里存的 config 也先递归解包再校验——旧客户端/中间层
    # 写入的字符串化嵌套字段在后台任务重放时一样能安全恢复。
    config = deep_unpack_json((await repo.get(run_id) or {}).get("input_json") or {})

    async def set_task(**kwargs: Any) -> None:
        if task_id is not None:
            await update_projection(task_repo, task_id, **kwargs)

    rec["status"] = "RUNNING"
    await _save(repo, rec)
    await set_task(status="running", progress_pct=8.0)
    await _update_layer(repo, rec, "E0", status="PASSED", finished_at=datetime.now(UTC).isoformat())
    await _update_layer(repo, rec, "E1", status="PASSED", finished_at=datetime.now(UTC).isoformat())
    await _update_layer(repo, rec, "E2", status="RUNNING", started_at=datetime.now(UTC).isoformat())
    try:
        body = ExplainerAssembleRequest.model_validate(config)
        # 🚨 v9.1: 工单沙盒 —— 每个 run 独立 data/workspace/{task_id}/ 目录,
        # 状态机(TaskRun)支持崩溃重试跳过已完成步骤;60–90s 试播也走同一沙盒。
        from hevi.core.workspace import WorkspaceManager

        task_id_ws = task_id or run_id
        ws = WorkspaceManager(task_id_ws, pipeline_type="main_remotion")
        ws.update_progress("running", 8)
        stock_service = None
        try:
            from hevi.sourcing.stock_search import StockAssetRepository, StockSearchService

            candidate = StockSearchService(StockAssetRepository(repo.pool))
            if candidate.available:
                stock_service = candidate
            else:
                logger.info("explainer assemble: PEXELS_API_KEY 未配置, stock_broll 跳过")
        except Exception as exc:
            logger.warning("explainer assemble: stock 服务不可用: %s", exc)
        result = await assemble_explainer_cues(
            body.topic_or_url or body.selected_hook,
            body.final_script_cues,
            ws.root,
            voice=body.voice_profile,
            enable_circle_avatar_mask=body.enable_circle_avatar_mask,
            enable_remotion_code_render=body.enable_remotion_code_render,
            enable_manim_render=body.enable_manim_render,
            enable_browser_broll=body.enable_browser_broll,
            aspect_ratio=body.aspect_ratio,
            heygen_presenter_id=body.heygen_presenter_id,
            presenter_provider=body.presenter_provider,
            presenter_name=body.presenter_name,
            presenter_image_url=body.presenter_image_url,
            presenter_reference_video=body.presenter_reference_video or None,
            preview_mode=bool(body.preview_mode),
            stock_service=stock_service,
            stock_user_id=str(rec.get("user_id") or "explainer_session"),
            source_text=body.source_text,
            reference_url=body.reference_url,
        )
        ws.mark_step_done("render", progress=100)
        manifest = result.engine_result.get("artifacts")
        decision_trail = result.engine_result.get("decision_trail") or []
        await _update_layer(
            repo, rec, "E2", status="PASSED", finished_at=datetime.now(UTC).isoformat()
        )
        await _finish_run(
            repo,
            rec,
            success=True,
            portrait_path=str(result.portrait_path),
            landscape_path=str(result.landscape_path),
            artifact_manifest={"artifacts": manifest or []},
            decision_trail=decision_trail,
        )
        await set_task(
            status="completed",
            progress_pct=100.0,
            result_video_path=str(result.portrait_path),
        )
    except Exception as exc:
        logger.exception("explainer assembled run %s failed", run_id)
        await _update_layer(
            repo,
            rec,
            "E2",
            status="FAILED",
            error=str(exc)[:500],
            finished_at=datetime.now(UTC).isoformat(),
        )
        await _finish_run(repo, rec, success=False, error=f"E2 failed: {exc}")
        await set_task(status="failed", error=f"E2 failed: {exc}")


async def execute_task(task: dict[str, Any], pool: PgPool) -> dict[str, Any]:
    """TaskService adapter entrypoint for explainer rendering."""
    config = task.get("config_json") or {}
    run_id = str(config.get("run_id") or "")
    if not run_id:
        raise ValueError("explainer task missing config_json.run_id")
    repo = AutomationRunRepository(pool)
    config = (await repo.get(run_id) or {}).get("input_json") or {}
    if config.get("mode") in {"deep_v6_assembled", "deep_v8_assembled"}:
        await _run_assembled_pipeline(repo, run_id)
    else:
        await _run_pipeline(repo, run_id)
    return await TaskRepository(pool).get_task(task["id"]) or task


def _rec_to_status(rec: dict[str, Any]) -> RunStatus:
    return RunStatus(
        run_id=rec["run_id"],
        status=rec["status"],
        topic=rec["topic"],
        created_at=rec["created_at"],
        completed_at=rec.get("completed_at"),
        current_layer=rec.get("current_layer"),
        layers=[LayerState(**value) for value in rec["layers"].values()],
        result_portrait_path=rec.get("result_portrait_path"),
        result_landscape_path=rec.get("result_landscape_path"),
        error=rec.get("error"),
        mode=rec.get("mode", "legacy"),
        artifact_manifest=rec.get("artifact_manifest"),
        decision_trail=rec.get("decision_trail") or [],
    )


def _capability_http_error(exc: ExplainerCapabilityError) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": exc.code,
            "message": exc.message,
            "action": exc.action,
        },
    )


@router.post("/research", response_model=ExplainerResearchJob, status_code=202)
async def research_explainer(
    body: ExplainerResearchRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> ExplainerResearchJob:
    """立刻派发异步研究任务并返回 202(根治长视频研究 524 超时)。

    同步跑完整研究(分章生成几百秒)会超 Cloudflare 100s 上限。这里改成:
    立刻设备一个 processing 状态信封到本地缓存,后台任务执行 research_and_generate,
    跑完覆盖成 ready + 完整确稿数据(或 failed + 错误);HTTP 连接秒回 202 + session_id。
    前端凭 session_id 轮询 GET /research/{session_id},status=ready 后进入确稿台。
    原断点续传语义不变:ready 的信封 payload 即完整的阶段一数据。
    """
    del user  # authentication is the boundary; research is stateless
    session_id = ensure_clean_session_id(body.session_id)
    # 先落盘 processing 信封:即使后台任务还没起在,前端轮询也能拿到状态。
    save_research_cache(
        session_id,
        status="processing",
        topic_or_url=body.topic_or_url[:20_000],
    )
    background_tasks.add_task(_run_research_job, body, session_id)
    return ExplainerResearchJob(
        session_id=session_id,
        status="processing",
        topic_or_url=body.topic_or_url[:20_000],
    )


async def _run_research_job(body: ExplainerResearchRequest, session_id: str) -> None:
    """后台执行研究:ready 覆盖成完整确稿数据,failed 记录错误供前端轮询。

    在 background_tasks 里跑,脱离请求生命周期 —— Cloudflare 就算掐断前端连接,
    后台仍会跑完并把 ready 信封写盘,前端重启后能凭 session_id 捞回结果。
    """
    try:
        result = await research_and_generate(body)
        payload = response_payload(result, body.topic_or_url)
        payload["session_id"] = session_id
        save_research_cache(
            session_id, status="ready", payload=payload, topic_or_url=body.topic_or_url[:20_000]
        )
    except ExplainerCapabilityError as exc:
        save_research_cache(
            session_id,
            status="failed",
            error=exc.message,
            topic_or_url=body.topic_or_url[:20_000],
        )
        logger.warning("explainer research job %s failed: %s", session_id, exc.message)
    except Exception as exc:  # background task, must not propagate
        save_research_cache(
            session_id,
            status="failed",
            error=f"研究后台任务异常: {exc}",
            topic_or_url=body.topic_or_url[:20_000],
        )
        logger.exception("explainer research job %s crashed", session_id)


@router.get("/research/{session_id}", response_model=ExplainerResearchJob)
async def get_research_cache(
    session_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> ExplainerResearchJob:
    """轮询研究任务状态信封:processing 继续等、ready 返回完整确稿 payload、failed 返回错误。

    复用原断点续传缓存(现升级为状态信封)。前端轮询此接口, Cloudflare 不会超时(秒级响应)。
    """
    del user
    cached = load_research_cache(session_id)
    if cached is None:
        raise HTTPException(status_code=404, detail="调研任务不存在(可能已过期或被清理)")
    try:
        return ExplainerResearchJob.model_validate({**cached, "session_id": session_id})
    except Exception as exc:
        logger.warning("explainer research cache %s 损坏: %s", session_id, exc)
        raise HTTPException(status_code=404, detail="调研缓存已损坏,请重新研究") from exc


def require_preview_gate(body: ExplainerAssembleRequest) -> None:
    """HTTP 闸:全片必须先试播并确认。库函数 assemble_explainer_cues 不拦。"""
    if not body.preview_mode and not body.preview_confirmed:
        raise HTTPException(
            status_code=409,
            detail="先出 60–90 秒试播并确认后再渲全片",
        )


def _parse_assemble_payload(raw: Any) -> ExplainerAssembleRequest:
    """隐患点 A 防爆解析:整体递归解包(藏在 str 里的 dict/list、双重序列化的
    嵌套字段全部还原)后再校验——字符串化 cue 绝不可能漏给 .get() 链式访问。
    """
    try:
        return ExplainerAssembleRequest.model_validate(deep_unpack_json(raw))
    except Exception as exc:
        logger.warning("explainer assemble 入参无法解析: %s", exc)
        raise HTTPException(status_code=422, detail=f"装配入参不合法: {exc}") from exc


@router.post("/validate-presenter-image", response_model=PresenterImageCheckResponse)
async def validate_presenter_image_endpoint(
    body: PresenterImageCheckRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> PresenterImageCheckResponse:
    """v9.1 素材质检:数字人底图合法性校验(可访问/尺寸/人脸占比)。

    用户在确稿台上传底图后,前端先把图片交给本地 AI 预检,提交前再调本
    接口做服务端权威校验 —— 双保险,拒绝无脸/超大图进入渲染队列。
    """
    del user
    from hevi.sourcing.asset_validator import validate_presenter_image as _validate

    verdict = await _validate(body.image_url)
    return PresenterImageCheckResponse(
        valid=verdict.valid,
        reason=verdict.reason,
        width=verdict.width,
        height=verdict.height,
        face_count=verdict.face_count,
        face_ratio=verdict.face_ratio,
        face_check=verdict.face_check,
    )


@router.post("/upload-presenter-image", response_model=PresenterImageCheckResponse)
async def upload_presenter_image_endpoint(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    file: Annotated[UploadFile, File(description="数字人底图(JPG/PNG,≤10MB)")],
) -> PresenterImageCheckResponse:
    """v9.1 确稿台底图上传:字节落盘 + 服务端权威质检,一步到位。

    前端 Dropzone 本地 AI 预检通过后上传;这里用与 URL 校验完全相同的
    ``_validate_bytes`` 逻辑复核(防绕过),通过则把图片落盘到
    ``output/presenter_images/<uuid>.jpg`` 并返回可读回的路径 —— 装配时
    ``presenter_image_url`` 直接传这个路径(本地读盘,不再二次下载)。
    """
    del user
    from hevi.sourcing.asset_validator import (
        MAX_DOWNLOAD_BYTES,
        validate_presenter_bytes,
    )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="空文件")
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise HTTPException(status_code=413, detail="图片超过 20MB 上限,请压缩后重试")

    verdict = validate_presenter_bytes(data)
    if not verdict.valid:
        raise HTTPException(status_code=422, detail=f"数字人底图不合规: {verdict.reason}")

    namespace = f"presenter-{uuid.uuid4()}"
    path = ReferenceStore().save_upload(
        namespace, file.filename or "presenter.png", data
    )
    return PresenterImageCheckResponse(
        valid=True,
        reason=path,
        width=verdict.width,
        height=verdict.height,
        face_count=verdict.face_count,
        face_ratio=verdict.face_ratio,
        face_check=verdict.face_check,
    )


@router.post("/assemble", response_model=ExplainerAssemblyAccepted, status_code=202)
async def assemble_explainer(
    request: Request,
    background_tasks: BackgroundTasks,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[AutomationRunRepository, Depends(get_run_repository)],
) -> ExplainerAssemblyAccepted:
    """Persist the approved cue sheet and dispatch one real production task.

    隐患点 A 防爆:入参先按原始 body 接收,整体递归解包再校验——不把字符串化
    字段漏给 cue.get(),也从根上杜绝 422 误伤可恢复数据。
    """
    body = _parse_assemble_payload(await request.json())
    require_preview_gate(body)
    # 🚨 v9.1: 素材质检前置拦截 —— presenter_image_url 不合法(不可访问/超大
    # 尺寸/无脸或多脸)直接 422 拒绝入队,不浪费渲染算力。
    if body.presenter_image_url:
        from hevi.sourcing.asset_validator import validate_presenter_image as _validate_image

        verdict = await _validate_image(body.presenter_image_url)
        if not verdict.valid:
            raise HTTPException(
                status_code=422,
                detail=f"数字人底图不合规: {verdict.reason}",
            )
    has_avatar_cue = any(
        cue.visual_type == "heygen_avatar" for cue in body.final_script_cues
    )
    if has_avatar_cue:
        await _bind_explainer_presenter(
            body,
            pool=repo.pool,
            user_id=str(user["id"]),
        )

    run_id = str(uuid.uuid4())
    binding = execution_binding("explainer", adapter_version="v8.0")
    topic = body.topic_or_url or body.selected_hook
    projection = await create_projection(
        TaskRepository(repo.pool),
        user_id=str(user["id"]),
        topic=topic,
        source=_KIND,
        video_provider=(
            body.presenter_provider if has_avatar_cue else "remotion"
        ),
        audio_provider=body.voice_profile,
        config={
            "run_id": run_id,
            "mode": "deep_v8_assembled",
            "engine_version": binding.engine_version,
            "adapter_version": binding.adapter_version,
        },
    )
    task_id = str(projection["id"])
    input_json = {
        **body.model_dump(mode="json"),
        "mode": "deep_v8_assembled",
        "run_id": run_id,
        "engine_version": binding.engine_version,
        "adapter_version": binding.adapter_version,
    }
    await repo.create(
        {
            "id": uuid.UUID(run_id),
            "kind": _KIND,
            "user_id": str(user["id"]),
            "status": "PENDING",
            "input_json": input_json,
            "state_json": {
                "mode": "deep_v8_assembled",
                "current_layer": None,
                "layers": _initial_layers(),
                "decision_trail": [
                    {"stage": "human_review", "outcome": "approved"},
                    {"stage": "dispatch", "adapter_version": binding.adapter_version},
                ],
            },
            "task_ids": [task_id],
        }
    )
    background_tasks.add_task(TaskService(TaskRepository(repo.pool)).run_task, uuid.UUID(task_id))
    return ExplainerAssemblyAccepted(
        task_id=task_id,
        status="processing",
        estimated_seconds=max(30, len(body.final_script_cues) * 12),
        sse_channel=f"/api/tasks/{task_id}/progress",
        engine_version=binding.engine_version,
        adapter_version=binding.adapter_version,
    )


@router.post("/run")
async def start_run(
    body: RunRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[AutomationRunRepository, Depends(get_run_repository)],
) -> dict[str, str]:
    if not body.topic.strip():
        raise HTTPException(status_code=422, detail="topic 不能为空")
    if len(body.topic) > 200:
        raise HTTPException(status_code=422, detail="选题过长(上限 200 字)")

    run_id = str(uuid.uuid4())
    task_ids: list[str] = []
    if isinstance(repo, AutomationRunRepository):
        projection = await create_projection(
            TaskRepository(repo.pool),
            user_id=str(user["id"]),
            topic=body.topic,
            source=_KIND,
            video_provider="explainer_adapter",
            audio_provider="explainer_adapter",
            config={"run_id": run_id},
        )
        task_ids = [str(projection["id"])]

    row = await repo.create(
        {
            "id": uuid.UUID(run_id),
            "kind": _KIND,
            "user_id": str(user["id"]),
            "status": "PENDING",
            "input_json": {"topic": body.topic},
            "state_json": {"current_layer": None, "layers": _initial_layers()},
            "task_ids": task_ids,
        }
    )
    run_id = str(row["id"])
    if task_ids:
        background_tasks.add_task(
            TaskService(TaskRepository(repo.pool)).run_task, uuid.UUID(task_ids[0])
        )
    else:
        background_tasks.add_task(_run_pipeline, repo, run_id)
    logger.info("explainer run %s started: %s", run_id, body.topic)
    return {"run_id": run_id, "status": "PENDING"}


@router.get("/runs")
async def list_runs(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[AutomationRunRepository, Depends(get_run_repository)],
) -> list[RunStatus]:
    rows = await repo.list_for_user(kind=_KIND, user_id=str(user["id"]))
    return [_rec_to_status(_record_from_row(row)) for row in rows]


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[AutomationRunRepository, Depends(get_run_repository)],
) -> RunStatus:
    return _rec_to_status(await _get_owned_run(repo, run_id, str(user["id"])))
