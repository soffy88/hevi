import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from hevi.core.config import settings
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
        "available_at": now,
        "scheduled_at": None,
        "scheduler_score": None,
        "scheduler_policy_version": None,
        "scheduler_decision_json": None,
        "updated_at": now
    })
    
    ahead = await repository.get_tasks_ahead(now)
    logger.info(f"Task {task_id} enqueued. Ahead: {ahead}")
    return ahead

async def dequeue(
    repository: TaskRepository,
    worker_id: str | None = None,
    *,
    resource_class: str = "any",
    available_vram_mb: int | None = None,
    capacity_slots: int = 1,
    provider_tokens: dict[str, int] | None = None,
    warm_providers: set[str] | None = None,
    scheduled_only: bool | None = None,
) -> dict[str, Any] | None:
    """Atomically claim the best eligible task for a worker pool."""
    return await repository.claim_next_queued_task(
        worker_id=worker_id,
        resource_class=resource_class,
        available_vram_mb=available_vram_mb,
        capacity_slots=capacity_slots,
        provider_tokens=provider_tokens,
        warm_providers=warm_providers,
        scheduled_only=(
            settings.scheduler_required if scheduled_only is None else scheduled_only
        ),
    )

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
