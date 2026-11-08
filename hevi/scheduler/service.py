"""Long-running scheduler loop with PostgreSQL leader election."""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from pathlib import Path

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
        self._retention_interval = float(
            os.getenv("HEVI_OUTPUT_RETENTION_INTERVAL_S", "86400")
        )
        self._retention_state = Path(
            os.getenv(
                "HEVI_OUTPUT_RETENTION_STATE",
                str(Path.home() / ".cache/hevi/output-retention-last-run"),
            )
        )
        # Persist the last *wall-clock* run: a restart must not reset the 24h
        # timer forever (S8 left 59 >30-day finals because it did).
        self._last_retention = self._read_last_retention()

    def _read_last_retention(self) -> float:
        try:
            return float(self._retention_state.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return 0.0  # never ran: run on the first iteration

    def _write_last_retention(self, when: float) -> None:
        try:
            self._retention_state.parent.mkdir(parents=True, exist_ok=True)
            self._retention_state.write_text(f"{when:.0f}\n", encoding="utf-8")
        except OSError:
            logger.warning("cannot persist retention timestamp at %s", self._retention_state)

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

    async def run_retention(self) -> dict[str, object] | None:
        """Daily output cleanup; only the elected leader runs it."""
        if not await self.repository.acquire_leader(
            settings.scheduler_leader_name,
            self.owner_id,
            lease_seconds=settings.scheduler_lease_seconds,
        ):
            return None
        from hevi.scheduler.retention import purge_intermediate_outputs

        try:
            summary = await asyncio.to_thread(purge_intermediate_outputs)
        except Exception:
            logger.exception("output retention failed")
            return None
        logger.info("output retention: %s", summary.as_dict())
        self._write_last_retention(time.time())
        return summary.as_dict()

    async def run(self) -> None:
        self._running = True
        logger.info("scheduler service started owner=%s", self.owner_id)
        while self._running:
            try:
                if time.time() - self._last_retention >= self._retention_interval:
                    summary = await self.run_retention()
                    if summary is not None:
                        self._last_retention = time.time()
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
