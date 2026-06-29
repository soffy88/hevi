import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from hevi.tasks.repository import TaskRepository

logger = logging.getLogger(__name__)

async def enqueue(repository: TaskRepository, task_id: uuid.UUID) -> int:
    """Put a task into the queue and return its position (ahead count)."""
    task = await repository.get_task(task_id)
    if not task:
        raise ValueError(f"Task {task_id} not found")
    
    now = datetime.now(UTC).replace(tzinfo=None)
    await repository.update_task(task_id, {
        "status": "queued",
        "queued_at": now,
        "updated_at": now
    })
    
    ahead = await repository.get_tasks_ahead(now)
    logger.info(f"Task {task_id} enqueued. Ahead: {ahead}")
    return ahead

async def dequeue(repository: TaskRepository) -> dict[str, Any] | None:
    """Atomically claim the next task (safe for concurrent workers)."""
    return await repository.claim_next_queued_task()

async def queue_position(repository: TaskRepository, task_id: uuid.UUID) -> int:
    """Return how many tasks are ahead of this task in the queue."""
    task = await repository.get_task(task_id)
    if not task or task["status"] != "queued" or not task["queued_at"]:
        return 0
    return await repository.get_tasks_ahead(task["queued_at"])

async def queue_status(repository: TaskRepository) -> dict[str, Any]:
    """Get current queue status."""
    count = await repository.get_queued_count()
    return {
        "queue_length": count,
        "is_active": True # Worker status could be added here if tracked
    }

async def estimate_wait(
    repository: TaskRepository, task_id: uuid.UUID, avg_task_time_s: int = 960
) -> int:
    """Estimate wait time in seconds (Default 16min = 960s)."""
    ahead = await queue_position(repository, task_id)
    return ahead * avg_task_time_s
