import asyncio
import contextlib
import inspect
import logging
import signal
import time
import uuid
from datetime import UTC, datetime

from obase.persistence import PgPool

from hevi.core.config import settings
from hevi.monitoring.metrics import (
    lease_expirations_total,
    task_attempt_duration_seconds,
    task_queue_latency_seconds,
    worker_utilization,
)
from hevi.queue.heartbeat import WorkerHeartbeat
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
        self._current_run_task: asyncio.Task[object] | None = None
        self.worker_id = f"worker-{uuid.uuid4()}"
        self._heartbeat = (
            WorkerHeartbeat(task_service.repository.pool, worker_id=self.worker_id)
            if isinstance(task_service.repository.pool, PgPool)
            else None
        )

    async def _heartbeat_loop(self) -> None:
        assert self._heartbeat is not None
        interval = max(1.0, float(settings.worker_heartbeat_interval_s))
        while self._running:
            try:
                await self._heartbeat.beat()
            except Exception:
                # A heartbeat outage must be visible to readiness, but must
                # not turn an otherwise recoverable worker into a crash loop.
                logger.exception("worker heartbeat persistence failed")
            await asyncio.sleep(interval)

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

    async def _reconcile_durable_executions(self) -> None:
        """Startup sweep of the durable provider plane (W17-A).

        Tasks carrying a persisted execution record are reported with their
        recovery action so operators (and the resume path) can see orphaned
        remote jobs and completed-but-undownloaded artifacts. Best-effort:
        never blocks the worker loop.
        """
        try:
            report = await self.task_service.reconcile_on_startup(limit=200)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("durable reconciliation: sweep failed: %s", exc)
            return
        counts = report.get("counts", {})
        pending = {
            key: value
            for key, value in counts.items()
            if key in {"resume_poll", "resume_download", "verify", "explicit_fail"}
        }
        if pending:
            logger.warning(
                "durable reconciliation: %d task(s) need attention: %s", report["total"], pending
            )
        else:
            logger.info("durable reconciliation: %d task(s) tracked, none pending", report["total"])
        # N06: resolve PENDING provider call rows from execution evidence.
        try:
            calls = await self.task_service.reconcile_call_rows(limit=500)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("call reconciliation: sweep failed: %s", exc)
            return
        if calls.get("changed"):
            logger.warning(
                "call reconciliation: %d/%d pending call row(s) terminalized",
                calls["changed"],
                calls["pending"],
            )
        else:
            logger.info(
                "call reconciliation: %d pending call row(s) stable", calls.get("pending", 0)
            )

    async def run(self) -> None:
        """Run the worker loop."""
        self._running = True
        heartbeat_task: asyncio.Task[None] | None = None
        if self._heartbeat is not None:
            try:
                await self._heartbeat.beat()
                heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            except Exception:
                logger.exception("worker heartbeat could not start")
        logger.info("Queue worker started")
        try:
            await self._recover_zombie_tasks()
            await self._reconcile_durable_executions()

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
                        self._current_run_task = asyncio.create_task(
                            self.task_service.run_task(task_id)
                        )
                        try:
                            result = await self._current_run_task
                            result_status = result.get("status") if isinstance(result, dict) else None
                            attempt_status = (
                                "success" if result_status in {"completed", "succeeded"} else "error"
                            )
                        except Exception as e:
                            logger.error(f"Error running task {self._current_task_id}: {e}")
                        finally:
                            self._current_run_task = None
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
        finally:
            self._running = False
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat_task
            if self._heartbeat is not None:
                with contextlib.suppress(Exception):
                    await self._heartbeat.mark_stopped()
            logger.info("Queue worker stopped")

    def stop(self) -> None:
        """Signal the worker to stop."""
        logger.info("Stopping queue worker...")
        self._running = False
        if self._current_run_task is not None and not self._current_run_task.done():
            # Do not let Docker's graceful-stop window turn a mid-run restart
            # into a completed run. The task remains running with its durable
            # attempt lease; the next worker recovers it after expiry.
            self._current_run_task.cancel()
