import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from hevi.cost import (
    HeviCostTracker,
    check_before_run,
    estimate_cost,
    monitor_during_run,
)
from hevi.observability import log_event, start_trace
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
        """Create a new video task, estimate cost, and persist it."""
        # 1. Estimate cost
        estimate = await estimate_cost(
            duration_archetype=duration_archetype,
            video_provider=video_provider,
            audio_provider=audio_provider,
            num_characters=kwargs.get("num_characters", 1),
        )

        # 2. Check limits (Circuit Breaker)
        await check_before_run(estimate)

        data = {
            "topic": topic,
            "duration_archetype": duration_archetype,
            "video_provider": video_provider,
            "audio_provider": audio_provider,
            "status": "pending",
            "progress_pct": 0.0,
            "config_json": {**kwargs, "estimated_usd": estimate.total_usd},
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        return await self.repository.create_task(data)

    async def run_task(self, task_id: uuid.UUID) -> dict[str, Any]:
        """Run a task using the orchestration pipeline with fallback and cost monitoring."""
        with start_trace(str(task_id)):
            log_event(stage="task_service", event="run_task_start", task_id=str(task_id))

            task = await self.repository.get_task(task_id)
            if not task:
                log_event(
                    stage="task_service",
                    event="task_not_found",
                    level="error",
                    task_id=str(task_id),
                )
                raise ValueError(f"Task {task_id} not found")

            # Update status to running
            await self.repository.update_task(
                task_id, {"status": "running", "updated_at": datetime.now(UTC)}
            )

            cost_tracker = HeviCostTracker()

            async def runner(provider: str) -> dict[str, Any]:
                # Monitor actual cost before each attempt (if applicable)
                await monitor_during_run(cost_tracker.total_usd)

                log_event(stage="task_service", event="orchestration_start", provider=provider)
                result = await orchestrate_longvideo(
                    topic=task["topic"],
                    duration_archetype=task["duration_archetype"],
                    video_provider=provider,
                    audio_provider=task["audio_provider"],
                    **task["config_json"],
                )

                # Record actual cost after success
                # M8 gives us duration_s
                cost_tracker.record_video(provider, result["duration"])
                # Assuming audio duration is similar
                cost_tracker.record_audio(task["audio_provider"], result["duration"] / 60.0)

                return result

            async def on_fallback(old_p: str, new_p: str, exc: Exception) -> None:
                log_event(
                    stage="task_service",
                    event="fallback_trigger",
                    old_provider=old_p,
                    new_provider=new_p,
                    error=str(exc),
                )
                # Re-estimate for the new provider
                new_est = await estimate_cost(
                    duration_archetype=task["duration_archetype"],
                    video_provider=new_p,
                    audio_provider=task["audio_provider"],
                )

                logger.warning(
                    f"Task {task_id} fallback: {old_p} -> {new_p}. "
                    f"New estimate: ${new_est.total_usd:.2f}"
                )

                await self.repository.update_task(
                    task_id,
                    {
                        "video_provider": new_p,
                        "error": f"Fallback from {old_p} due to: {exc}",
                        "config_json": {**task["config_json"], "estimated_usd": new_est.total_usd},
                        "updated_at": datetime.now(UTC),
                    },
                )

            try:
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
                    "error": None,
                    "updated_at": datetime.now(UTC),
                    # Record final actual cost in metadata
                    "config_json": {**task["config_json"], "actual_usd": cost_tracker.total_usd},
                }
                await self.repository.update_task(task_id, update_data)
                log_event(
                    stage="task_service", event="run_task_completed", result_url=result["url"]
                )
                return {**task, **update_data}

            except Exception as e:
                log_event(
                    stage="task_service", event="run_task_failed", level="error", error=str(e)
                )
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
