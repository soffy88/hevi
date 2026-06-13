import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from hevi.pipeline import orchestrate_longvideo
from hevi.tasks.repository import TaskRepository

logger = logging.getLogger(__name__)


class TaskService:
    def __init__(self, repository: TaskRepository):
        self.repository = repository

    async def create_task(
        self,
        topic: str,
        duration_archetype: str,
        video_provider: str,
        audio_provider: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create a new video task and persist it."""
        data = {
            "topic": topic,
            "duration_archetype": duration_archetype,
            "video_provider": video_provider,
            "audio_provider": audio_provider,
            "status": "pending",
            "progress_pct": 0.0,
            "config_json": kwargs,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        return await self.repository.create_task(data)

    async def run_task(self, task_id: uuid.UUID) -> dict[str, Any]:
        """Run a task using the orchestration pipeline."""
        task = await self.repository.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        # Update status to running
        await self.repository.update_task(
            task_id, {"status": "running", "updated_at": datetime.now(UTC)}
        )

        try:
            # Call orchestration core (M8 wrapper)
            result = await orchestrate_longvideo(
                topic=task["topic"],
                duration_archetype=task["duration_archetype"],
                video_provider=task["video_provider"],
                audio_provider=task["audio_provider"],
                **task["config_json"],
            )

            # Task level completion
            update_data = {
                "status": "completed",
                "progress_pct": 100.0,
                "result_video_path": result["url"],
                "total_shots": result["metadata"].get("shots", 0),
                "completed_shots": result["metadata"].get("shots", 0),
                "updated_at": datetime.now(UTC),
            }
            await self.repository.update_task(task_id, update_data)
            return {**task, **update_data}

        except Exception as e:
            logger.exception(f"Task {task_id} failed")
            update_data = {
                "status": "failed",
                "error": str(e),
                "updated_at": datetime.now(UTC),
            }
            await self.repository.update_task(task_id, update_data)
            return {**task, **update_data}

    async def resume_task(self, task_id: uuid.UUID) -> dict[str, Any]:
        """Resume a failed or paused task."""
        task = await self.repository.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        if task["status"] in ("completed", "running"):
            return task

        # M8 is currently a black box for shots, so we resume by re-running the task.
        return await self.run_task(task_id)

    async def get_task_status(self, task_id: uuid.UUID) -> dict[str, Any] | None:
        """Get the current status of a task."""
        return await self.repository.get_task(task_id)
