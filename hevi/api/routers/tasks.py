from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from obase.persistence import PgPool

from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.tasks.progress import get_task_progress_stream
from hevi.tasks.repository import TaskRepository

router = APIRouter(prefix="/tasks", tags=["tasks"])


async def get_pg_pool() -> PgPool:
    """Dependency to get the PostgreSQL pool."""
    return await get_hevi_pg_pool()


async def get_repository(pool: Annotated[PgPool, Depends(get_pg_pool)]) -> TaskRepository:
    """Dependency to get the task repository."""
    return TaskRepository(pool)


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
