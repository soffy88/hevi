"""Regression tests for the no-fake-production capability boundary."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from hevi.api.routers.pro_studio import LiveBody, StockBody, livestream_start, stock_search
from hevi.api.routers.production_tools_v2 import SeedanceRequest, seedance
from hevi.api.routers.voice_studio import PersonalityRequest, rewrite_personality
from hevi.digital_human.duix_service import DuixLiveService
from hevi.production.capabilities import capability_catalog
from hevi.sourcing.stock_search import StockSearchService


def _assert_unavailable(exc: pytest.ExceptionInfo[HTTPException], capability_id: str) -> None:
    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "CAPABILITY_UNAVAILABLE"
    assert exc.value.detail["id"] == capability_id


@pytest.mark.asyncio
async def test_generation_surfaces_do_not_fabricate_task_ids_when_unwired() -> None:
    with pytest.raises(HTTPException) as stock_error:
        await stock_search(
            body=StockBody(query="city"),
            user={"id": "user-1"},
            service=StockSearchService(AsyncMock(), api_key=""),
        )
    assert stock_error.value.status_code == 503
    assert stock_error.value.detail["capability_id"] == "stock_search"

    with pytest.raises(HTTPException) as live_error:
        await livestream_start(
            LiveBody(avatar_id="avatar-1", script="hello"),
            {},
            DuixLiveService(base_url=""),
        )
    assert live_error.value.status_code == 503
    assert live_error.value.detail["capability_id"] == "livestream"

    service = AsyncMock()
    service.create_production.return_value = {"id": "real-task", "status": "pending"}
    service.submit_task.return_value = {"id": "real-task", "status": "queued"}
    result = await seedance(
        SeedanceRequest(prompt="a city"), {"id": "user-1"}, service, AsyncMock()
    )
    assert result["task_id"] == "real-task"


@pytest.mark.asyncio
async def test_voice_rewrite_does_not_claim_unchanged_text_is_model_output() -> None:
    with pytest.raises(HTTPException) as error:
        await rewrite_personality(PersonalityRequest(text="原始文案", persona="documentary"), _={})
    _assert_unavailable(error, "voice_studio_rewrite")


def test_capability_catalog_covers_truthful_unavailable_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The developer checkout may contain a real .env. Keep this assertion
    # about the unconfigured boundary deterministic and independent of it.
    monkeypatch.delenv("VOICEBOX_BASE_URL", raising=False)
    monkeypatch.delenv("GEN_ENGINE_BASE_URL", raising=False)
    by_id = {item["id"]: item for item in capability_catalog()}
    assert by_id["explainer"]["available"] is True
    assert by_id["voice_studio_tts"]["status"] == "unavailable"
    assert by_id["livestream"]["setup"]
