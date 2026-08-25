"""Long-running scheduler loop with PostgreSQL leader election."""

from __future__ import annotations

import asyncio
import logging
import uuid

from hevi.core.config import settings
from hevi.execution import ResourceSnapshot
from hevi.scheduler.repository import SchedulerRepository

logger = logging.getLogger(__name__)


class SchedulerService:
    def __init__(
        self,
        repository: SchedulerRepository,
        *,
        owner_id: str | None = None,
        poll_interval: float | None = None,
    ) -> None:
        self.repository = repository
        self.owner_id = owner_id or f"scheduler-{uuid.uuid4()}"
        self.poll_interval = poll_interval or settings.scheduler_poll_interval_s
        self._running = False

    def stop(self) -> None:
        self._running = False

    async def run_once(self) -> int:
        if not await self.repository.acquire_leader(
            settings.scheduler_leader_name,
            self.owner_id,
            lease_seconds=settings.scheduler_lease_seconds,
        ):
            return 0
        resources = ResourceSnapshot(
            worker_id=settings.scheduler_worker_id,
            resource_class=settings.worker_resource_class,
            available_vram_mb=settings.worker_available_vram_mb,
            capacity_slots=max(1, settings.scheduler_candidate_limit),
        )
        return await self.repository.schedule_once(
            resources,
            candidate_limit=settings.scheduler_candidate_limit,
        )

    async def run(self) -> None:
        self._running = True
        logger.info("scheduler service started owner=%s", self.owner_id)
        while self._running:
            try:
                scheduled = await self.run_once()
                if scheduled:
                    logger.info("scheduler dispatched %d task(s)", scheduled)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("scheduler iteration failed")
            await asyncio.sleep(self.poll_interval)
        logger.info("scheduler service stopped")


__all__ = ["SchedulerService"]
