"""Durable provider health sampling for the policy engine."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence

from oprim.provider_health_check import provider_health_check

from hevi.core.config import settings
from hevi.video.capability_guard import PROVIDER_LIMITS

from .repository import ProviderStateRepository

logger = logging.getLogger(__name__)
HealthProbe = Callable[[str], Awaitable[bool]]


class ProviderHealthService:
    """Sample provider reachability and persist routing inputs.

    The sampler is deliberately independent from API and worker lifecycles.
    A failed probe becomes a low health score, while probe exceptions are
    recorded as unhealthy rather than silently retaining stale availability.
    """

    def __init__(
        self,
        repository: ProviderStateRepository,
        *,
        provider_ids: Sequence[str] | None = None,
        probe: HealthProbe = provider_health_check,
        poll_interval: float = 60.0,
    ) -> None:
        self.repository = repository
        self.provider_ids = tuple(provider_ids or PROVIDER_LIMITS)
        self.probe = probe
        self.poll_interval = poll_interval
        self._running = False

    async def sample_once(self) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for provider_id in self.provider_ids:
            started = time.monotonic()
            try:
                healthy = bool(await self.probe(provider_id))
            except Exception:
                logger.exception("provider health probe failed: %s", provider_id)
                healthy = False
            results[provider_id] = healthy
            await self.repository.upsert(
                provider_id,
                health=1.0 if healthy else 0.0,
                p95_latency_ms=(time.monotonic() - started) * 1000.0,
                source="health_probe",
            )
        return results

    async def run(self) -> None:
        self._running = True
        logger.info("provider health service started interval=%ss", self.poll_interval)
        while self._running:
            try:
                await self.sample_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("provider health sampling iteration failed")
            await asyncio.sleep(self.poll_interval)

    def stop(self) -> None:
        self._running = False


async def run_provider_health_service() -> None:
    from hevi.db.pg_pool import get_hevi_pg_pool

    pool = await get_hevi_pg_pool()
    await ProviderHealthService(
        ProviderStateRepository(pool),
        poll_interval=settings.provider_health_poll_interval_s,
    ).run()


__all__ = ["ProviderHealthService", "run_provider_health_service"]
