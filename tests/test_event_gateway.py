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
async def test_gateway_filters_subscribed_resources() -> None:
    manager = ConnectionManager()
    subscribed = _FakeWebSocket()
    other = _FakeWebSocket()
    await manager.connect(subscribed)
    await manager.connect(other)
    aggregate_id = uuid4()
    await manager.set_subscription(subscribed, {str(aggregate_id)})
    await manager.set_subscription(other, {str(uuid4())})

    await EventGateway(manager).publish(
        DomainEvent(
            event_type="production.updated",
            aggregate_id=aggregate_id,
            payload={"production_id": str(aggregate_id)},
        )
    )

    # The gateway resource is the durable aggregate id. The generic manager
    # remains independently testable with arbitrary resource identifiers.
    assert len(subscribed.messages) == 1
    assert other.messages == []


@pytest.mark.asyncio
async def test_manager_broadcasts_legacy_task_updates_to_unfiltered_clients() -> None:
    manager = ConnectionManager()
    client = _FakeWebSocket()
    await manager.connect(client)

    await manager.broadcast_task_update("task-1", "running", 42, stage="render")

    assert '"type": "task_update"' in client.messages[0]
    assert '"progress": 42' in client.messages[0]
