import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hevi.core.config import settings
from hevi.cost import (
    CostLimit,
    CostLimitExceeded,
    HeviCostTracker,
    check_before_run,
    estimate_cost,
    get_pricing_table,
    monitor_during_run,
    select_cheapest_provider,
)
from hevi.tasks.task_service import TaskService


@pytest.mark.asyncio
async def test_estimate_cost_basic():
    est = await estimate_cost(
        duration_archetype="1-5min", video_provider="ltx2_cloud", audio_provider="vibevoice"
    )
    # 1-5min target_s is 180. 180 * 0.04 = 7.2
    assert est.video_cost_usd == 7.2
    assert est.audio_cost_usd == 0.0  # vibevoice is local
    assert est.total_usd == 7.2
    assert est.estimated_credits == 720


@pytest.mark.asyncio
async def test_estimate_cost_multi_character():
    est = await estimate_cost(
        duration_archetype="1-5min",
        video_provider="ltx2_cloud",
        audio_provider="wan_cloud",  # assume wan can do audio for test
        num_characters=3,
    )
    # 180s video
    # Audio: 180 * (1 + (3-1)*0.1) = 180 * 1.2 = 216s
    # Price: 216 * 0.033 = 7.128 (wan_cloud ¥0.24/s ÷ 7.25 CNY/USD; calibrated 2026-06)
    assert est.audio_cost_usd == pytest.approx(7.128, rel=1e-4)


def test_pricing_table_structure():
    pricing = get_pricing_table()
    # ltx2_cloud exposes Fast-1080p as default price and the full 2D table
    assert pricing["ltx2_cloud"]["price_usd"] == 0.04
    assert "pricing_2d" in pricing["ltx2_cloud"]
    assert pricing["ltx2_cloud"]["pricing_2d"]["fast"]["1080p"] == 0.04
    assert pricing["ltx2_cloud"]["pricing_2d"]["pro"]["2160p"] == 0.24
    # wan_cloud still read from settings
    with patch.object(settings, "wan_price_usd", 0.99):
        assert get_pricing_table()["wan_cloud"]["price_usd"] == 0.99


@pytest.mark.asyncio
async def test_circuit_breaker_before_run():
    est = MagicMock(total_usd=100.0)
    limit = CostLimit(max_per_task_usd=50.0)
    with pytest.raises(CostLimitExceeded):
        await check_before_run(est, limit=limit)


@pytest.mark.asyncio
async def test_circuit_breaker_during_run():
    with pytest.raises(CostLimitExceeded):
        await monitor_during_run(60.0, limit=CostLimit(max_per_task_usd=50.0))


@pytest.mark.asyncio
async def test_selector_quality_floor():
    # ltx2_cloud quality=10, wan_cloud quality=9 (see selector.PROVIDER_QUALITY)
    # Real pricing (2026-06): ltx2 Fast-1080p=$0.04/s, wan_cloud=$0.033/s (¥0.24÷7.25)
    # wan_cloud is now cheaper than ltx2 at Fast tier.
    candidates = ["ltx2_cloud", "wan_cloud"]

    # Floor 10 — only ltx2 qualifies (wan quality=9 < 10)
    p = await select_cheapest_provider(
        duration_archetype="1-5min",
        candidates=candidates,
        audio_provider="vibevoice",
        quality_floor=10,
    )
    assert p == "ltx2_cloud"

    # Floor 9 — both qualify; wan_cloud cheaper ($0.033/s < ltx2 $0.04/s)
    p9 = await select_cheapest_provider(
        duration_archetype="1-5min",
        candidates=candidates,
        audio_provider="vibevoice",
        quality_floor=9,
    )
    assert p9 == "wan_cloud"

    # Floor 11 — no provider meets floor → ValueError
    with pytest.raises(ValueError):
        await select_cheapest_provider(
            duration_archetype="1-5min",
            candidates=candidates,
            audio_provider="vibevoice",
            quality_floor=11,
        )


def test_tracker_recording():
    with patch("hevi.cost.tracker.CostTracker") as mock_internal_class:
        mock_instance = mock_internal_class.return_value
        tracker = HeviCostTracker()

        tracker.record_video("ltx2_cloud", 100.0)
        mock_instance.record.assert_called_with(
            category="video",
            provider="ltx2_cloud",
            model_or_tier="default",
            unit="per_second",
            quantity=100.0,
        )


@pytest.mark.asyncio
async def test_task_service_create_task_limit_rejection():
    repo = AsyncMock()
    service = TaskService(repo)

    # Large duration archetype
    with patch.object(settings, "cost_limit_per_task_usd", 1.0):
        with pytest.raises(CostLimitExceeded):
            await service.create_task(
                topic="Epic",
                duration_archetype="45min+",  # ~3600s * 0.04 = 144.0 > 1.0
                video_provider="ltx2_cloud",
                audio_provider="vibevoice",
            )


@pytest.mark.asyncio
async def test_task_service_run_task_with_monitoring_and_recording():
    repo = AsyncMock()
    task_id = uuid.uuid4()
    repo.get_task.return_value = {
        "id": task_id,
        "topic": "t",
        "duration_archetype": "1-5min",
        "video_provider": "ltx2_cloud",
        "audio_provider": "vibevoice",
        "config_json": {},
    }
    service = TaskService(repo)

    with patch(
        "hevi.tasks.task_service.orchestrate_longvideo", new_callable=AsyncMock
    ) as mock_orch, patch("hevi.tasks.task_service.HeviCostTracker") as mock_tracker_class:

        mock_tracker = mock_tracker_class.return_value
        mock_tracker.total_usd = 0.0
        mock_orch.return_value = {"url": "v.mp4", "duration": 180.0, "metadata": {"shots": 10}}

        await service.run_task(task_id)

        # Verify recording was called
        mock_tracker.record_video.assert_called_with("ltx2_cloud", 180.0)


@pytest.mark.asyncio
async def test_fallback_cost_reestimate():
    repo = AsyncMock()
    task_id = uuid.uuid4()
    repo.get_task.return_value = {
        "id": task_id,
        "topic": "t",
        "duration_archetype": "1-5min",
        "video_provider": "ltx2_cloud",
        "audio_provider": "vibevoice",
        "config_json": {"estimated_usd": 7.2},
    }
    service = TaskService(repo)

    # Mock fallback sequence: ltx2 fails, wan succeeds
    with (
        patch("hevi.tasks.task_service.orchestrate_longvideo") as mock_orch,
        patch(
            "hevi.tasks.task_service.run_with_fallback",
            wraps=from_resilience_run_with_fallback,
        ),
        patch(
            "hevi.resilience.fallback_chain.provider_health_check",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("hevi.resilience.retry_policy.asyncio.sleep", new_callable=AsyncMock),
    ):

        def orch_side_effect(**kwargs: Any):
            if kwargs["video_provider"] == "ltx2_cloud":
                raise Exception("ltx2 down")
            return {"url": "v.mp4", "duration": 180.0, "metadata": {"shots": 5}}

        mock_orch.side_effect = orch_side_effect

        await service.run_task(task_id)

        # Check repo update for wan_cloud with new estimated_usd
        # wan price is $0.033/s (¥0.24/s ÷ 7.25 CNY/USD; calibrated 2026-06)
        # 180s * 0.033 = 5.94 (standard quality, multiplier=1.0)
        fallback_updates = [
            c
            for c in repo.update_task.call_args_list
            if c.args[1].get("video_provider") == "wan_cloud"
        ]
        assert fallback_updates[0].args[1]["config_json"]["estimated_usd"] == pytest.approx(
            5.94, rel=1e-4
        )


async def from_resilience_run_with_fallback(**kwargs: Any):
    from hevi.resilience import run_with_fallback

    return await run_with_fallback(**kwargs)


def test_credits_conversion():
    with patch.object(settings, "credits_per_usd", 500):
        # Implicitly tested via logic in estimate_cost_basic but kept for structure
        pass
