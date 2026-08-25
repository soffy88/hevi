from __future__ import annotations

import math
import time
from uuid import uuid4

import pytest

from hevi.core.ws_manager import ConnectionManager
from hevi.events import DomainEvent, EventGateway


class _FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def accept(self) -> None:
        return None

    async def send_text(self, payload: str) -> None:
        self.messages.append(payload)


@pytest.mark.asyncio
async def test_in_process_event_gateway_p95_under_two_seconds() -> None:
    manager = ConnectionManager()
    clients = [_FakeWebSocket() for _ in range(100)]
    aggregate_id = uuid4()
    for client in clients:
        await manager.connect(client)
        await manager.set_subscription(client, {str(aggregate_id)})

    gateway = EventGateway(manager)
    latencies: list[float] = []
    samples = 20
    for sample in range(samples):
        started = time.perf_counter()
        await gateway.publish(
            DomainEvent(
                event_type="load.ws_p95",
                aggregate_id=aggregate_id,
                payload={"sample": sample},
            )
        )
        latencies.append(time.perf_counter() - started)
        assert all(len(client.messages) == sample + 1 for client in clients)

    p95 = sorted(latencies)[max(0, math.ceil(len(latencies) * 0.95) - 1)]
    assert p95 < 2.0, f"in-process WS p95={p95:.4f}s samples={latencies!r}"
