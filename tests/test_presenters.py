from unittest.mock import AsyncMock

import pytest

from hevi.api.routers.presenters import test_presenter as run_presenter_check


@pytest.mark.asyncio
async def test_presenter_test_reports_missing_on_camera_assets() -> None:
    repo = AsyncMock()
    repo.get.return_value = {
        "id": "p-1",
        "motion": "talking_head",
        "lipsync": "dedicated_lipsync",
        "performance": "narrator",
        "delivery_json": {},
    }

    result = await run_presenter_check("p-1", user={"id": "u-1"}, repo=repo)

    assert result["ready"] is False
    assert len(result["issues"]) == 2


@pytest.mark.asyncio
async def test_presenter_test_accepts_voice_over_without_subject() -> None:
    repo = AsyncMock()
    repo.get.return_value = {
        "id": "p-2",
        "motion": "voice_over",
        "lipsync": "none",
        "performance": "narrator",
        "delivery_json": {"aspect_ratio": "9:16"},
    }

    result = await run_presenter_check("p-2", user={"id": "u-1"}, repo=repo)

    assert result["ready"] is True
    assert result["strategy"]["delivery"]["aspect_ratio"] == "9:16"
