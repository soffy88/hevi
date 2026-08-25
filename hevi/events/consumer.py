"""常驻、可重试的 per-instance domain-event consumer."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable

from obase.persistence import PgPool

from hevi.monitoring.metrics import outbox_events_total

from .outbox import DomainEvent, OutboxRepository

logger = logging.getLogger(__name__)
EventHandler = Callable[[DomainEvent], Awaitable[None]]


class EventConsumer:
    """Read the immutable event log once per API instance.

    Each instance owns a separate cursor, so a published event fans out to
    every WebSocket process.  A failed handler leaves the cursor unchanged;
    after the configured number of attempts the event is advanced into the
    durable DLQ and later events are allowed to flow.
    """

    def __init__(
        self,
        pool: PgPool,
        handler: EventHandler,
        *,
        consumer_name: str | None = None,
        poll_interval: float = 0.5,
        batch_size: int = 100,
        max_attempts: int = 8,
        aggregate_id: uuid.UUID | None = None,
    ) -> None:
        self.repository = OutboxRepository(pool)
        self.handler = handler
        self.consumer_name = consumer_name or f"api-{uuid.uuid4()}"
        self.poll_interval = poll_interval
        self.batch_size = batch_size
        self.max_attempts = max_attempts
        self.aggregate_id = aggregate_id
        self._running = False

    def stop(self) -> None:
        self._running = False

    async def consume_once(self) -> int:
        events = await self.repository.read_consumer_batch(
            self.consumer_name,
            limit=self.batch_size,
            aggregate_id=self.aggregate_id,
        )
        processed = 0
        for event in events:
            try:
                await self.handler(event)
            except Exception as exc:
                dead_lettered = await self.repository.record_failure(
                    event.id, str(exc), max_attempts=self.max_attempts
                )
                outbox_events_total.labels(
                    operation="consume", status="dead_letter" if dead_lettered else "retry"
                ).inc()
                if not dead_lettered:
                    raise
                logger.error("event %s moved to DLQ after handler failure", event.id)
            await self.repository.advance_consumer(self.consumer_name, event)
            processed += 1
        return processed

    async def run(self) -> None:
        self._running = True
        logger.info("event consumer started name=%s", self.consumer_name)
        while self._running:
            try:
                await self.consume_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("event consumer iteration failed")
            await asyncio.sleep(self.poll_interval)
        logger.info("event consumer stopped name=%s", self.consumer_name)


__all__ = ["EventConsumer"]
