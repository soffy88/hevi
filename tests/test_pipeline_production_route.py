import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks, HTTPException

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


@pytest.mark.asyncio
async def test_automatic_local_media_request_is_normalized_by_backend() -> None:
    task_id = uuid.uuid4()
    svc = AsyncMock()
    svc.create_production.return_value = {"id": task_id, "status": "pending"}
    svc.submit_task.return_value = {"id": task_id, "status": "queued"}

    await create_production(
        ProductionRequest(
            source="automatic",
            topic="local golden path",
            video_provider="auto",
            audio_provider="vibevoice",
            options={"visual_mode": "local_media"},
        ),
        user={"id": uuid.uuid4()},
        svc=svc,
        background_tasks=BackgroundTasks(),
    )

    request = svc.create_production.await_args.args[0]
    assert request.source == "local_media"
    assert request.video_provider == "remotion"
    assert request.audio_provider == "edge_tts"
    assert request.options["requested_capability"] == "local_media"
    assert request.options["voice_identity"] == {"voice_id": "zh_female_standard"}


@pytest.mark.asyncio
async def test_v2v_request_is_rejected_before_production_graph_submission() -> None:
    svc = AsyncMock()
    with pytest.raises(HTTPException) as error:
        await create_production(
            ProductionRequest(
                source="automatic",
                topic="blocked v2v",
                options={"visual_mode": "v2v"},
            ),
            user={"id": uuid.uuid4()},
            svc=svc,
            background_tasks=BackgroundTasks(),
        )

    assert error.value.status_code == 409
    assert error.value.detail["status"] == "WIRING_QUALIFIED_PROVIDER_BLOCKED"
    svc.create_production.assert_not_awaited()
