from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from hevi.runs.task_projection import create_projection, update_projection
from hevi.tasks.repository import TaskRepository


@pytest.mark.asyncio
async def test_create_projection_marks_adapter_source() -> None:
    repo = TaskRepository(MagicMock())
    task_id = uuid4()
    repo.create_task = AsyncMock(return_value={"id": task_id})  # type: ignore[method-assign]

    result = await create_projection(
        repo,
        user_id="u-1",
        topic="一句话解说",
        source="explainer",
        config={"presenter_id": "p-1"},
    )

    assert result["id"] == task_id
    payload = repo.create_task.await_args.args[0]
    assert payload["config_json"] == {
        "production_source": "explainer",
        "presenter_id": "p-1",
    }


@pytest.mark.asyncio
async def test_update_projection_writes_final_media_and_status() -> None:
    repo = TaskRepository(MagicMock())
    repo.update_task = AsyncMock(return_value=True)  # type: ignore[method-assign]

    await update_projection(
        repo,
        uuid4(),
        status="completed",
        progress_pct=100.0,
        result_video_path="output/explainer/portrait.mp4",
    )

    values = repo.update_task.await_args.args[1]
    assert values["status"] == "completed"
    assert values["progress_pct"] == 100.0
    assert values["result_video_path"].endswith("portrait.mp4")
