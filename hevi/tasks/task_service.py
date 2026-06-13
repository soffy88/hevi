import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from hevi.pipeline import orchestrate_longvideo
from hevi.resilience import RetryPolicy, run_with_fallback
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
        """Run a task using the orchestration pipeline with fallback and retry."""
        task = await self.repository.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        # Update status to running
        await self.repository.update_task(
            task_id, {"status": "running", "updated_at": datetime.now(UTC)}
        )

        async def runner(provider: str) -> dict[str, Any]:
            # This factory will be called by with_retry inside run_with_fallback
            return await orchestrate_longvideo(
                topic=task["topic"],
                duration_archetype=task["duration_archetype"],
                video_provider=provider,
                audio_provider=task["audio_provider"],
                **task["config_json"],
            )

        async def on_fallback(old_p: str, new_p: str, exc: Exception) -> None:
            # Log fallback event and update current provider in DB
            logger.warning(f"Task {task_id} falling back: {old_p} -> {new_p} due to {exc}")
            await self.repository.update_task(
                task_id,
                {
                    "video_provider": new_p,
                    "error": f"Fallback from {old_p} due to: {exc}",
                    "updated_at": datetime.now(UTC),
                },
            )

        try:
            # Default policy: 3 attempts, 2s base delay
            result = await run_with_fallback(
                initial_provider=task["video_provider"],
                runner=runner,
                on_fallback=on_fallback,
                retry_policy=RetryPolicy(),
            )

            # Task level completion
            update_data = {
                "status": "completed",
                "progress_pct": 100.0,
                "result_video_path": result["url"],
                "total_shots": result["metadata"].get("shots", 0),
                "completed_shots": result["metadata"].get("shots", 0),
                "error": None, # Clear any previous fallback errors
                "updated_at": datetime.now(UTC),
            }
            await self.repository.update_task(task_id, update_data)
            return {**task, **update_data}

        except Exception as e:
            logger.exception(f"Task {task_id} failed after all fallbacks")
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
