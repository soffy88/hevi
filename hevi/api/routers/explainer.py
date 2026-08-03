"""Self-media explainer adapter.

The adapter owns only its E0-E2 planning state.  That state is persisted in
``automation_runs`` so a process restart never makes a submitted run invisible.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from obase.persistence import PgPool
from pydantic import BaseModel

from hevi.auth.dependencies import get_current_user
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.explainer.contracts import (
    ExplainerAssembleRequest,
    ExplainerAssemblyAccepted,
    ExplainerCapabilityError,
    ExplainerResearchRequest,
    ExplainerResearchResponse,
)
from hevi.explainer.research import research_and_generate, response_payload
from hevi.presenters.repository import PresenterRepository
from hevi.production.execution import execution_binding
from hevi.runs.repository import AutomationRunRepository
from hevi.runs.task_projection import create_projection, update_projection
from hevi.tasks.repository import TaskRepository
from hevi.tasks.task_service import TaskService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/explainer", tags=["explainer"])
_KIND = "explainer"
_LAYER_ORDER = ["E0", "E1", "E2"]


class RunRequest(BaseModel):
    topic: str


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
        result = await render_narrated_storyboard(storyboard, Path("output/explainer") / run_id)
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
    config = (await repo.get(run_id) or {}).get("input_json") or {}

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
        result = await assemble_explainer_cues(
            body.topic_or_url or body.selected_hook,
            body.final_script_cues,
            Path("output/explainer") / run_id,
            voice=body.voice_profile,
            enable_circle_avatar_mask=body.enable_circle_avatar_mask,
            enable_remotion_code_render=body.enable_remotion_code_render,
            enable_browser_broll=body.enable_browser_broll,
            aspect_ratio=body.aspect_ratio,
            heygen_presenter_id=body.heygen_presenter_id,
            presenter_provider=body.presenter_provider,
            presenter_name=body.presenter_name,
        )
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


@router.post("/research", response_model=ExplainerResearchResponse)
async def research_explainer(
    body: ExplainerResearchRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> ExplainerResearchResponse:
    """Research one topic and return a progressive hook matrix plus editable scripts."""
    del user  # authentication is the boundary; research is stateless
    try:
        result = await research_and_generate(body)
    except ExplainerCapabilityError as exc:
        raise _capability_http_error(exc) from exc
    return ExplainerResearchResponse.model_validate(response_payload(result, body.topic_or_url))


@router.post("/assemble", response_model=ExplainerAssemblyAccepted, status_code=202)
async def assemble_explainer(
    body: ExplainerAssembleRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[AutomationRunRepository, Depends(get_run_repository)],
) -> ExplainerAssemblyAccepted:
    """Persist the approved cue sheet and dispatch one real production task."""
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
