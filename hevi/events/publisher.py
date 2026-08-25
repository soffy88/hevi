"""Small replay-safe outbox publisher loop primitive."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress

from hevi.monitoring.metrics import outbox_events_total

from .outbox import DomainEvent, OutboxRepository

EventHandler = Callable[[DomainEvent], Awaitable[None]]
logger = logging.getLogger(__name__)


class OutboxPublisher:
    def __init__(self, repository: OutboxRepository, handler: EventHandler) -> None:
        self.repository = repository
        self.handler = handler
        self._running = False

    async def publish_once(self, limit: int = 100) -> int:
        events = await self.repository.claim_unpublished(limit=limit)
        if not events:
            return 0
        claim_token = events[0].claim_token
        try:
            for event in events:
                await self.handler(event)
        except Exception as exc:
            outbox_events_total.labels(operation="publish", status="error").inc(len(events))
            for event in events:
                with suppress(Exception):
                    await self.repository.record_failure(event.id, str(exc))
            if claim_token is not None:
                await self.repository.release_claim(claim_token)
            raise
        return await self.repository.mark_published(
            [event.id for event in events], claim_token=claim_token
        )

    def stop(self) -> None:
        self._running = False

    async def run(self, *, poll_interval: float = 0.5, batch_size: int = 100) -> None:
        """Run as a separately deployable outbox publisher process."""

        self._running = True
        while self._running:
            try:
                await self.publish_once(limit=batch_size)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("outbox publisher iteration failed")
            await asyncio.sleep(poll_interval)


__all__ = ["EventHandler", "OutboxPublisher"]
