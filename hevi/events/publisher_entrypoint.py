"""Standalone transactional-outbox publisher.

PostgreSQL remains the durable event log.  Redis Streams is only the broker
fan-out transport; an event is marked published after the stream append
 succeeds, so a broker outage leaves the outbox replayable.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from dotenv import load_dotenv

from hevi.core.config import settings
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.events.outbox import DomainEvent, OutboxRepository
from hevi.events.publisher import OutboxPublisher

logger = logging.getLogger(__name__)


async def run() -> None:
    load_dotenv()
    if not settings.event_publisher_enabled:
        logger.info("event publisher disabled")
        return
    pool = await get_hevi_pg_pool()
    broker = None
    try:
        from redis.asyncio import Redis

        broker = Redis.from_url(settings.redis_url, decode_responses=True)

        async def publish(event: DomainEvent) -> None:
            await broker.xadd(
                settings.event_stream_name,
                {
                    "event_id": str(event.id),
                    "event_type": event.event_type,
                    "aggregate_id": str(event.aggregate_id),
                    "payload": event.model_dump_json(),
                },
                maxlen=100_000,
                approximate=True,
            )

        publisher = OutboxPublisher(OutboxRepository(pool), publish)
        try:
            await publisher.run(
                poll_interval=settings.event_publisher_poll_interval_s,
                batch_size=settings.event_publisher_batch_size,
            )
        finally:
            publisher.stop()
    finally:
        if broker is not None:
            with suppress(Exception):
                await broker.aclose()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())


if __name__ == "__main__":
    main()
