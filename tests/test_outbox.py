from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from hevi.events import DomainEvent, OutboxPublisher


@pytest.mark.asyncio
async def test_outbox_publisher_acknowledges_only_after_handler() -> None:
    repository = AsyncMock()
    claim_token = uuid4()
    event = DomainEvent(
        event_type="production.updated", aggregate_id=uuid4(), claim_token=claim_token
    )
    repository.claim_unpublished.return_value = [event]
    repository.mark_published.return_value = 1
    handler = AsyncMock()

    published = await OutboxPublisher(repository, handler).publish_once()

    assert published == 1
    handler.assert_awaited_once_with(event)
    repository.mark_published.assert_awaited_once_with([event.id], claim_token=claim_token)
    repository.release_claim.assert_not_awaited()


@pytest.mark.asyncio
async def test_outbox_publisher_releases_claim_on_handler_failure() -> None:
    repository = AsyncMock()
    claim_token = uuid4()
    event = DomainEvent(
        event_type="production.updated", aggregate_id=uuid4(), claim_token=claim_token
    )
    repository.claim_unpublished.return_value = [event]
    handler = AsyncMock(side_effect=RuntimeError("broker unavailable"))

    with pytest.raises(RuntimeError, match="broker unavailable"):
        await OutboxPublisher(repository, handler).publish_once()

    repository.release_claim.assert_awaited_once_with(claim_token)
    repository.mark_published.assert_not_awaited()
