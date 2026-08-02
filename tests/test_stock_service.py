from unittest.mock import AsyncMock

import httpx
import pytest

from hevi.sourcing.stock_search import StockProviderUnavailable, StockSearchService


@pytest.mark.asyncio
async def test_pexels_video_results_are_normalized_and_persisted() -> None:
    repository = AsyncMock()
    repository.record_many.return_value = [{"id": "saved-1", "provider": "pexels"}]
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "videos": [
                    {
                        "id": 42,
                        "url": "https://www.pexels.com/video/42/",
                        "image": "https://cdn.example/thumb.jpg",
                        "user": {"name": "Alice"},
                        "video_files": [{"link": "https://cdn.example/video.mp4"}],
                    }
                ]
            },
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        service = StockSearchService(repository, api_key="key", client=client)
        result = await service.search(user_id="user-1", query="city", media_type="video", count=10)

    assert result == [{"id": "saved-1", "provider": "pexels"}]
    assets = repository.record_many.await_args.kwargs["assets"]
    assert assets[0]["source_url"] == "https://www.pexels.com/video/42/"
    assert assets[0]["license"]["name"] == "Pexels License"
    assert assets[0]["license"]["author"] == "Alice"


@pytest.mark.asyncio
async def test_stock_search_without_key_is_unavailable() -> None:
    service = StockSearchService(AsyncMock(), api_key="")
    with pytest.raises(StockProviderUnavailable, match="PEXELS_API_KEY"):
        await service.search(user_id="user-1", query="city", media_type="video", count=1)
