import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hevi.cost import (
    HeviCostTracker,
    check_before_run,
    estimate_cost,
    monitor_during_run,
)
from hevi.credits.billing_service import BillingService
from hevi.observability import log_event, start_trace
from hevi.pipeline import orchestrate_longvideo
from hevi.resilience import RetryPolicy, run_with_fallback
from hevi.tasks.repository import TaskRepository

logger = logging.getLogger(__name__)


class TaskService:
    def __init__(self, repository: TaskRepository, billing_svc: BillingService | None = None):
        self.repository = repository
        self.billing_svc = billing_svc

    async def create_task(
        self,
        topic: str,
        duration_archetype: str,
        video_provider: str,
        audio_provider: str,
        user_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create a new video task, estimate cost, check credits, and persist it."""
        # 1. Estimate cost (USD)
        estimate = await estimate_cost(
            duration_archetype=duration_archetype,
            video_provider=video_provider,
            audio_provider=audio_provider,
            num_characters=kwargs.get("num_characters", 1),
        )

        # 2. Check limits (Circuit Breaker)
        await check_before_run(estimate)

        # 3. Credit Check (SaaS-2)
        credits_needed = 0
        if self.billing_svc and user_id:
            credits_needed = await self.billing_svc.estimate_credits(
                duration_archetype=duration_archetype,
                video_provider=video_provider,
                **kwargs
            )
            await self.billing_svc.check_and_reserve(user_id, credits_needed)

        data = {
            "topic": topic,
            "user_id": user_id,
            "duration_archetype": duration_archetype,
            "video_provider": video_provider,
            "audio_provider": audio_provider,
            "status": "pending",
            "progress_pct": 0.0,
            "total_shots": 0,
            "completed_shots": 0,
            "config_json": {
                **kwargs, 
                "estimated_usd": estimate.total_usd,
                "credits_reserved": credits_needed
            },
            "created_at": datetime.now(UTC).replace(tzinfo=None),
            "updated_at": datetime.now(UTC).replace(tzinfo=None),
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

            user_id = task.get("user_id")
            credits_reserved = task["config_json"].get("credits_reserved", 0)

            # Update status to running
            await self.repository.update_task(
                task_id, {"status": "running", "updated_at": datetime.now(UTC).replace(tzinfo=None)}
            )

            # 4. Consume credits at the start of execution (SaaS-2)
            if self.billing_svc and user_id and credits_reserved > 0:
                try:
                    await self.billing_svc.consume(user_id, credits_reserved, str(task_id))
                except Exception as exc:
                    logger.error(f"Credit consumption failed for task {task_id}: {exc}")
                    # If consumption fails (e.g. balance changed since creation), fail task
                    update_data = {
                        "status": "failed",
                        "error": f"Credit settlement failed: {exc}",
                        "updated_at": datetime.now(UTC).replace(tzinfo=None),
                    }
                    await self.repository.update_task(task_id, update_data)
                    return {**task, **update_data}

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
                    output_dir=Path("output/tasks") / str(task_id),
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
                        "updated_at": datetime.now(UTC).replace(tzinfo=None),
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
                    "updated_at": datetime.now(UTC).replace(tzinfo=None),
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

                # 5. Refund credits on failure (SaaS-2)
                if self.billing_svc and user_id and credits_reserved > 0:
                    try:
                        await self.billing_svc.refund(user_id, credits_reserved, str(task_id))
                    except Exception as refund_exc:
                        logger.error(f"Credit refund failed for task {task_id}: {refund_exc}")

                update_data = {
                    "status": "failed",
                    "error": str(e),
                    "updated_at": datetime.now(UTC).replace(tzinfo=None),
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
