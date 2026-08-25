"""Translate durable domain events into WebSocket gateway messages."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from hevi.core.ws_manager import ConnectionManager
from hevi.monitoring.metrics import ws_event_lag_seconds

from .outbox import DomainEvent


class EventGateway:
    """Connection-layer adapter; it never owns production state."""

    def __init__(self, manager: ConnectionManager) -> None:
        self.manager = manager

    async def publish(self, event: DomainEvent) -> None:
        payload: dict[str, Any] = {
            "type": "domain_event",
            "event_id": str(event.id),
            "event_type": event.event_type,
            "schema_version": event.schema_version,
            "occurred_at": event.occurred_at.isoformat(),
            "aggregate_type": event.aggregate_type,
            "aggregate_id": str(event.aggregate_id),
            "payload": event.payload,
        }
        await self.manager.broadcast_event(payload, resource_id=str(event.aggregate_id))
        occurred_at = event.occurred_at
        now = datetime.now(UTC) if occurred_at.tzinfo is not None else datetime.now(UTC).replace(
            tzinfo=None
        )
        ws_event_lag_seconds.labels(event_type=event.event_type).observe(
            max(0.0, (now - occurred_at).total_seconds())
        )

    async def publish_replay(self, events: list[DomainEvent]) -> int:
        for event in events:
            await self.publish(event)
        return len(events)


__all__ = ["EventGateway"]
