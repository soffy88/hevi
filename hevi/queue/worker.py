import asyncio
import contextlib
import inspect
import logging
import signal
import time
import uuid
from datetime import UTC, datetime

from hevi.core.config import settings
from hevi.monitoring.metrics import (
    lease_expirations_total,
    task_attempt_duration_seconds,
    task_queue_latency_seconds,
    worker_utilization,
)
from hevi.queue.task_queue import dequeue
from hevi.tasks.attempt_repository import AttemptRepository
from hevi.tasks.task_service import TaskService

logger = logging.getLogger(__name__)


def _task_class(task: dict[str, object]) -> str:
    config = task.get("config_json") or {}
    source = config.get("production_source") if isinstance(config, dict) else None
    return str(source or task.get("duration_archetype") or "unknown")


def _queue_age_seconds(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        queued_at = value
    else:
        try:
            queued_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if queued_at.tzinfo is not None:
        now = datetime.now(UTC)
    else:
        now = datetime.now(UTC).replace(tzinfo=None)
    return max(0.0, (now - queued_at).total_seconds())


class QueueWorker:
    def __init__(
        self,
        task_service: TaskService,
        poll_interval: float = 5.0,
        *,
        resource_class: str = "any",
        available_vram_mb: int | None = None,
        capacity_slots: int = 1,
        provider_tokens: dict[str, int] | None = None,
        warm_providers: set[str] | None = None,
    ):
        self.task_service = task_service
        self.poll_interval = poll_interval
        self.resource_class = resource_class
        self.available_vram_mb = available_vram_mb
        self.capacity_slots = capacity_slots
        self.provider_tokens = provider_tokens or {}
        self.warm_providers = warm_providers or set()
        self._running = False
        self._current_task_id = None
        self.worker_id = f"worker-{uuid.uuid4()}"

    async def _recover_zombie_tasks(self) -> None:
        """Recover only tasks whose durable lease has actually expired.

        A running status alone is not evidence of a zombie: a rolling deployment
        may leave a healthy worker executing.  Lease expiry is the ownership
        signal; expired work becomes ``interrupted`` for explicit recovery.
        """
        repo = self.task_service.repository
        if self.task_service.attempt_repository is not None:
            try:
                recovered = await AttemptRepository(repo.pool).recover_expired(limit=100)
                if recovered:
                    lease_expirations_total.labels(task_class="durable_attempt").inc(len(recovered))
                    logger.warning(
                        "attempt recovery: requeued %d expired attempt(s)", len(recovered)
                    )
                return
            except Exception as exc:
                logger.error("attempt recovery: failed to query durable attempts: %s", exc)
                return
        try:
            acquire = repo.pool.acquire()
            if not hasattr(acquire, "__aenter__"):
                if inspect.iscoroutine(acquire):
                    acquire.close()
                logger.debug("lease recovery: pool does not expose an async acquire context")
                return
            async with acquire as conn:
                rows = await conn.fetch(
                    "SELECT id, lease_token, duration_archetype FROM video_tasks "
                    "WHERE status IN ('running', 'claimed') "
                    "AND lease_until IS NOT NULL AND lease_until < NOW() "
                    "AND (heartbeat_at IS NULL OR heartbeat_at < NOW() - interval '30 seconds')"
                )
        except Exception as exc:
            logger.error("zombie recovery: failed to query running tasks: %s", exc)
            return

        # Unit/local adapters may expose an async mock or a lazy row iterator;
        # recovery must remain best-effort and never prevent the worker loop.
        try:
            rows = list(rows)
        except TypeError:
            logger.debug("lease recovery: pool returned no iterable rows")
            return

        if not rows:
            logger.info("zombie recovery: no zombie tasks found")
            return

        logger.warning("lease recovery: found %d expired task(s)", len(rows))
        for row in rows:
            task_id = row["id"]
            lease_expirations_total.labels(
                task_class=str(row.get("duration_archetype") or "unknown")
            ).inc()
            try:
                await repo.update_task(
                    task_id,
                    {
                        "status": "interrupted",
                        "error": "lease expired: worker ownership lost; recovery required",
                        "updated_at": datetime.now(UTC).replace(tzinfo=None),
                    },
                )
                await repo.clear_lease(task_id, row["lease_token"])
                logger.info("lease recovery: task %s → interrupted", task_id)
            except Exception as exc:
                logger.error("zombie recovery: failed for task %s: %s", task_id, exc)

    async def run(self) -> None:
        """Run the worker loop."""
        self._running = True
        logger.info("Queue worker started")
        await self._recover_zombie_tasks()

        # Setup signal handlers for graceful shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            # Signal handlers not supported on all platforms (e.g. Windows)
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, self.stop)

        while self._running:
            try:
                # Recovery is a live part of the worker loop, not only a
                # startup migration.  A healthy sibling worker must be able
                # to take over after another worker dies without restarting.
                await self._recover_zombie_tasks()
                task = await dequeue(
                    self.task_service.repository,
                    self.worker_id,
                    resource_class=self.resource_class,
                    available_vram_mb=self.available_vram_mb,
                    capacity_slots=self.capacity_slots,
                    provider_tokens=self.provider_tokens,
                    warm_providers=self.warm_providers,
                    scheduled_only=settings.scheduler_required,
                )
                if task:
                    task_id = task["id"]
                    self._current_task_id = task_id
                    task_class = _task_class(task)
                    queued_age = _queue_age_seconds(task.get("queued_at"))
                    if queued_age is not None:
                        task_queue_latency_seconds.labels(
                            task_class=task_class, resource_class=self.resource_class
                        ).observe(queued_age)
                    worker_utilization.labels(resource_class=self.resource_class).set(
                        min(1.0, 1.0 / max(1, self.capacity_slots))
                    )
                    attempt_started = time.monotonic()
                    attempt_status = "error"
                    logger.info(f"Processing task {task_id}")
                    try:
                        result = await self.task_service.run_task(task_id)
                        result_status = result.get("status") if isinstance(result, dict) else None
                        attempt_status = (
                            "success"
                            if result_status in {"completed", "succeeded"}
                            else "error"
                        )
                    except Exception as e:
                        logger.error(f"Error running task {self._current_task_id}: {e}")
                    finally:
                        task_attempt_duration_seconds.labels(
                            task_class=task_class, status=attempt_status
                        ).observe(time.monotonic() - attempt_started)
                        worker_utilization.labels(resource_class=self.resource_class).set(0.0)
                        self._current_task_id = None
                else:
                    await asyncio.sleep(self.poll_interval)
            except Exception as e:
                logger.error(f"Worker loop error: {e}")
                await asyncio.sleep(self.poll_interval)

        logger.info("Queue worker stopped")

    def stop(self) -> None:
        """Signal the worker to stop."""
        logger.info("Stopping queue worker...")
        self._running = False
