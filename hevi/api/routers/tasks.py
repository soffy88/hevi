from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from obase.persistence import PgPool
from pydantic import BaseModel

from hevi.auth.dependencies import get_current_user
from hevi.auth.jwt_handler import decode_access_token
from hevi.credits.account_service import AccountService
from hevi.credits.billing_service import BillingService, InsufficientCredits
from hevi.credits.repository import CreditRepository
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.tasks.progress import get_task_progress_stream
from hevi.tasks.repository import TaskRepository
from hevi.tasks.task_service import TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])


# ── Request schemas ───────────────────────────────────────────────────────────


class LongVideoRequest(BaseModel):
    topic: str
    duration_archetype: str
    video_provider: str = "ltx2_cloud"
    audio_provider: str = "vibevoice"
    num_characters: int = 1
    quality_profile: str = "standard"
    style_preset: str | None = None


class EstimateRequest(BaseModel):
    duration_archetype: str
    video_provider: str = "ltx2_cloud"
    audio_provider: str = "vibevoice"
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


# ── Routes ────────────────────────────────────────────────────────────────────


async def _create_task(
    body: LongVideoRequest,
    user: dict[str, Any],
    svc: TaskService,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    try:
        task = await svc.create_task(
            topic=body.topic,
            duration_archetype=body.duration_archetype,
            video_provider=body.video_provider,
            audio_provider=body.audio_provider,
            user_id=str(user["id"]),
            num_characters=body.num_characters,
        )
        # Decision: Enqueue local tasks, run cloud tasks immediately in background
        task = await svc.submit_task(task["id"])
        
        if task["status"] != "queued":
            background_tasks.add_task(svc.run_task, task["id"])
            
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


@router.post("", status_code=201)
async def create_task_alias(
    body: LongVideoRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[TaskService, Depends(get_task_service)],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    return await _create_task(body, user, svc, background_tasks)


@router.post("/longvideo", status_code=201)
async def create_longvideo_task(
    body: LongVideoRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[TaskService, Depends(get_task_service)],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    return await _create_task(body, user, svc, background_tasks)


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
    background_tasks.add_task(svc.resume_task, task_id)
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
