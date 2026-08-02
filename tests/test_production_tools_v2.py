from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks, HTTPException

from hevi.api.routers import production_tools_v2 as tools


@pytest.mark.asyncio
async def test_seedance_creates_canonical_task() -> None:
    service = AsyncMock()
    service.create_production.return_value = {"id": "task-1", "status": "pending"}
    service.submit_task.return_value = {"id": "task-1", "status": "queued"}
    result = await tools.seedance(
        tools.SeedanceRequest(prompt="a cinematic city"),
        {"id": "user-1"},
        service,
        BackgroundTasks(),
    )
    assert result["task_id"] == "task-1"
    request = service.create_production.await_args.args[0]
    assert request.source == "automatic"
    assert request.options["workbench_operation"] == "seedance_generate"


@pytest.mark.asyncio
async def test_clip_video_is_explicitly_unavailable() -> None:
    with pytest.raises(HTTPException) as exc:
        await tools.clip_video(tools.ClipRequest(video_path="/tmp/input.mp4"), {"id": "user-1"})
    assert exc.value.status_code == 503
    assert exc.value.detail["capability_id"] == "clip_video"
