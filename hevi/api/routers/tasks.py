from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from obase.persistence import PgPool
from pydantic import BaseModel

from hevi.auth.dependencies import get_current_user
from hevi.credits.account_service import AccountService
from hevi.credits.billing_service import BillingService
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


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post("/longvideo", status_code=201)
async def create_longvideo_task(
    body: LongVideoRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[TaskService, Depends(get_task_service)],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Create and start a long video task."""
    try:
        task = await svc.create_task(
            topic=body.topic,
            duration_archetype=body.duration_archetype,
            video_provider=body.video_provider,
            audio_provider=body.audio_provider,
            user_id=str(user["id"]),
            num_characters=body.num_characters,
        )
        # Run in background
        background_tasks.add_task(svc.run_task, task["id"])
        return task
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # Check if it's InsufficientCredits (could use custom exception mapper but simpler here)
        if "Insufficient credits" in str(exc):
            raise HTTPException(status_code=402, detail=str(exc)) from exc
        raise


@router.get("/{task_id}")
async def get_task_details(
    task_id: UUID, repo: Annotated[TaskRepository, Depends(get_repository)]
) -> dict[str, Any]:
    """Retrieve task details and status."""
    task = await repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/{task_id}/progress")
async def stream_task_progress(
    task_id: UUID, repo: Annotated[TaskRepository, Depends(get_repository)]
) -> StreamingResponse:
    """SSE endpoint for task progress tracking."""
    # First check if task exists
    task = await repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return StreamingResponse(
        get_task_progress_stream(task_id, repo), media_type="text/event-stream"
    )
