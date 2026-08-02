from unittest.mock import AsyncMock, MagicMock

import pytest

from hevi.production.contracts import ProductionRequest
from hevi.tasks.task_service import TaskService


def test_production_request_compiles_all_modes_to_one_task_boundary() -> None:
    request = ProductionRequest(
        source="shortdrama",
        topic="主角在雨夜发现真相",
        subject_ids=["sub-1", "sub-2"],
        presenter_id="presenter-1",
        options={"subtitle_style": "large_white"},
    )

    args = request.to_task_args()

    assert args["production_source"] == "shortdrama"
    assert args["num_characters"] == 2
    assert args["character_subject_ids"] == ["sub-1", "sub-2"]
    assert args["presenter_id"] == "presenter-1"
    assert args["subtitle_style"] == "large_white"


@pytest.mark.asyncio
async def test_new_production_persists_execution_binding_before_scheduling() -> None:
    service = TaskService(MagicMock())
    service.create_task = AsyncMock(return_value={"id": "task-1"})

    await service.create_production(
        ProductionRequest(source="explainer", topic="一句话解释前景理论"),
        user_id="user-1",
    )

    kwargs = service.create_task.await_args.kwargs
    binding = kwargs["execution_binding"]
    assert binding["capability_id"] == "explainer"
    assert binding["engine"] == "oservi.production_execution"
    assert binding["engine_version"]
