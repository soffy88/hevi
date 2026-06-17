import asyncio
import json
from collections.abc import AsyncGenerator
from uuid import UUID

from hevi.queue.task_queue import estimate_wait, queue_position
from hevi.tasks.repository import TaskRepository


async def get_task_progress_stream(
    task_id: UUID, repository: TaskRepository, interval_s: float = 2.0
) -> AsyncGenerator[str]:
    """SSE stream for task progress."""
    while True:
        task = await repository.get_task(task_id)
        if not task:
            yield f"data: {json.dumps({'error': 'Task not found'})}\n\n"
            break

        payload = {
            "task_id": str(task_id),
            "status": task["status"],
            "progress_pct": task["progress_pct"],
            "completed_shots": task.get("completed_shots", 0),
            "total_shots": task.get("total_shots", 0),
        }

        if task["status"] == "queued":
            ahead = await queue_position(repository, task_id)
            wait_s = await estimate_wait(repository, task_id)
            payload.update({
                "queue_position": ahead,
                "ahead": ahead,
                "estimated_wait_s": wait_s,
                "message": f"Queued. {ahead} tasks ahead. Estimated wait: {wait_s // 60}m"
            })

        if task.get("error"):
            payload["error"] = task["error"]
        if task.get("result_video_path"):
            payload["result_video_path"] = task["result_video_path"]

        yield f"data: {json.dumps(payload)}\n\n"

        if task["status"] in ("completed", "failed"):
            break

        await asyncio.sleep(interval_s)
