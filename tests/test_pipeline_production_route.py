import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks

from hevi.api.routers.pipeline import UnifiedGenerateRequest, create_production, generate_unified
from hevi.production.contracts import ProductionRequest


@pytest.mark.asyncio
async def test_pipeline_production_uses_one_task_lifecycle() -> None:
    task_id = uuid.uuid4()
    svc = AsyncMock()
    svc.create_production.return_value = {"id": task_id, "status": "pending"}
    svc.submit_task.return_value = {"id": task_id, "status": "queued"}

    result = await create_production(
        ProductionRequest(source="explainer", topic="一句话讲清楚量子纠缠"),
        user={"id": uuid.uuid4()},
        svc=svc,
        background_tasks=BackgroundTasks(),
    )

    assert result["task_id"] == str(task_id)
    assert result["production_source"] == "explainer"
    svc.create_production.assert_awaited_once()
    svc.submit_task.assert_awaited_once_with(task_id)


@pytest.mark.asyncio
async def test_unified_generate_maps_hub_contract_to_standard_task() -> None:
    task_id = uuid.uuid4()
    svc = AsyncMock()
    svc.create_production.return_value = {"id": task_id, "status": "pending"}
    svc.submit_task.return_value = {"id": task_id, "status": "queued"}

    result = await generate_unified(
        UnifiedGenerateRequest(
            source_channel="hub_quick",
            adapter_type="explainer",
            config={
                "prompt": "前景理论",
                "duration_archetype": "1-5min",
                "aspect_ratio": "9:16",
                "execution_preset": "fast",
                "character_references": ["subject-1"],
            },
        ),
        user={"id": uuid.uuid4()},
        svc=svc,
        background_tasks=BackgroundTasks(),
    )

    assert result["task_id"] == str(task_id)
    assert result["production_source"] == "explainer"
    request = svc.create_production.await_args.args[0]
    assert request.source == "explainer"
    assert request.options["source_channel"] == "hub_quick"
    assert request.options["execution_preset"] == "fast"
    assert request.subject_ids == ["subject-1"]
