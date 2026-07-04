import asyncio
import contextlib
import logging
import signal
from datetime import UTC, datetime

from hevi.queue.task_queue import dequeue
from hevi.tasks.task_service import TaskService

logger = logging.getLogger(__name__)


class QueueWorker:
    def __init__(self, task_service: TaskService, poll_interval: float = 5.0):
        self.task_service = task_service
        self.poll_interval = poll_interval
        self._running = False
        self._current_task_id = None

    async def _recover_zombie_tasks(self) -> None:
        """On startup: mark tasks stuck in 'running' as failed and refund credits.

        Tasks left in 'running' state after a container restart had their credits
        consumed (billing_service.consume was called) but the refund on failure
        never triggered. Without recovery, those credits are permanently lost and
        users hit 402 on next attempt.
        """
        repo = self.task_service.repository
        billing = self.task_service.billing_svc
        try:
            async with repo.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT id, user_id, config_json FROM video_tasks "
                    "WHERE status IN ('running', 'claimed')"
                )
        except Exception as exc:
            logger.error("zombie recovery: failed to query running tasks: %s", exc)
            return

        if not rows:
            logger.info("zombie recovery: no zombie tasks found")
            return

        logger.warning("zombie recovery: found %d zombie task(s)", len(rows))
        for row in rows:
            task_id = row["id"]
            user_id = str(row["user_id"]) if row["user_id"] else None
            try:
                await repo.update_task(
                    task_id,
                    {
                        "status": "failed",
                        "error": "zombie: worker restarted while task was running",
                        "updated_at": datetime.now(UTC).replace(tzinfo=None),
                    },
                )
                # Refund only what was actually consumed (idempotent; a task can be
                # 'running'/'claimed' before consume() ran → no over-refund).
                if billing and user_id:
                    res = await billing.refund_for_task(user_id, str(task_id))
                    logger.info(
                        "zombie recovery: task %s → failed, refunded %s to %s",
                        task_id,
                        res.get("refunded", 0),
                        user_id,
                    )
                else:
                    logger.info("zombie recovery: task %s → failed (no user)", task_id)
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
                task = await dequeue(self.task_service.repository)
                if task:
                    task_id = task["id"]
                    self._current_task_id = task_id
                    logger.info(f"Processing task {task_id}")
                    try:
                        await self.task_service.run_task(task_id)
                    except Exception as e:
                        logger.error(f"Error running task {self._current_task_id}: {e}")
                    finally:
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
