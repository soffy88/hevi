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
    check_daily_budget,
    check_series_budget,
    estimate_cost,
    get_pricing_table,
    get_series_spend_usd,
    get_todays_spend_usd,
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


# 三层预算熔断第3层(HEVI 路线图 Phase1 #30):全局每日聚合上限。


@pytest.mark.asyncio
async def test_get_todays_spend_usd_sums_actual_cost():
    pool = MagicMock()
    with patch(
        "obase.persistence.query", new_callable=AsyncMock, return_value=[{"total": 12.5}]
    ) as mock_query:
        total = await get_todays_spend_usd(pool)
    assert total == 12.5
    mock_query.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_daily_budget_noop_when_unconfigured():
    pool = MagicMock()
    with patch("obase.persistence.query", new_callable=AsyncMock) as mock_query:
        await check_daily_budget(pool, additional_usd=999.0, daily_budget_usd=None)
    mock_query.assert_not_awaited()  # 未配置 → 连查都不查,不是查了但放行


@pytest.mark.asyncio
async def test_check_daily_budget_raises_when_exceeded():
    pool = MagicMock()
    with patch("obase.persistence.query", new_callable=AsyncMock, return_value=[{"total": 18.0}]):
        with pytest.raises(CostLimitExceeded):
            await check_daily_budget(pool, additional_usd=5.0, daily_budget_usd=20.0)


@pytest.mark.asyncio
async def test_check_daily_budget_passes_within_limit():
    pool = MagicMock()
    with patch("obase.persistence.query", new_callable=AsyncMock, return_value=[{"total": 5.0}]):
        await check_daily_budget(pool, additional_usd=5.0, daily_budget_usd=20.0)  # 不抛


@pytest.mark.asyncio
async def test_task_service_create_task_respects_daily_budget():
    repo = AsyncMock()
    service = TaskService(repo)
    with (
        patch.object(settings, "daily_budget_usd", 5.0),
        patch("obase.persistence.query", new_callable=AsyncMock, return_value=[{"total": 4.0}]),
    ):
        with pytest.raises(CostLimitExceeded):
            await service.create_task(
                topic="t",
                duration_archetype="1-5min",  # 180s * 0.04 = $7.2,4+7.2 > 5.0
                video_provider="ltx2_cloud",
                audio_provider="vibevoice",
            )


# SPEC-001 §6:季级预算熔断(独立于全局日预算,按 series_id 聚合)。


@pytest.mark.asyncio
async def test_get_series_spend_usd_sums_actual_cost():
    pool = MagicMock()
    with patch(
        "obase.persistence.query", new_callable=AsyncMock, return_value=[{"total": 8.0}]
    ) as mock_query:
        total = await get_series_spend_usd(pool, series_id="series-1")
    assert total == 8.0
    mock_query.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_series_budget_noop_when_unconfigured():
    pool = MagicMock()
    with patch("obase.persistence.query", new_callable=AsyncMock) as mock_query:
        await check_series_budget(
            pool, series_id="series-1", additional_usd=999.0, series_budget_usd=None
        )
    mock_query.assert_not_awaited()  # 该季没配预算 → 连查都不查


@pytest.mark.asyncio
async def test_check_series_budget_raises_when_exceeded():
    pool = MagicMock()
    with patch("obase.persistence.query", new_callable=AsyncMock, return_value=[{"total": 18.0}]):
        with pytest.raises(CostLimitExceeded):
            await check_series_budget(
                pool, series_id="series-1", additional_usd=5.0, series_budget_usd=20.0
            )


@pytest.mark.asyncio
async def test_check_series_budget_passes_within_limit():
    pool = MagicMock()
    with patch("obase.persistence.query", new_callable=AsyncMock, return_value=[{"total": 5.0}]):
        await check_series_budget(
            pool, series_id="series-1", additional_usd=5.0, series_budget_usd=20.0
        )  # 不抛


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

    with (
        patch("hevi.tasks.task_service.orchestrate_longvideo", new_callable=AsyncMock) as mock_orch,
        patch("hevi.tasks.task_service.HeviCostTracker") as mock_tracker_class,
    ):
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


# ── §7-2 成本感知路由 v1 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_route_filters_capability_and_health():
    """路由候选 = 能力支持 mode ∧ 活状态可路由;欠费的被排除。"""
    from unittest.mock import patch as _patch

    from hevi.cost import router as R
    from hevi.resilience import live_state

    live_state._reset_for_tests()
    try:
        for _ in range(live_state._WINDOW):  # veo3 灌满 403 → 不可路由
            live_state.record_provider_outcome("veo3", is_403=True)
        cap = {}

        async def fake_cheapest(**kw):
            cap["candidates"] = kw["candidates"]
            return kw["candidates"][0]

        with _patch("hevi.cost.router.select_cheapest_provider", fake_cheapest):
            chosen = await R.route_video_provider(
                duration_archetype="short", audio_provider="vibevoice", mode="t2v"
            )
        assert "veo3" not in cap["candidates"]  # 欠费排除
        assert "ltx2_cloud" in cap["candidates"]  # 可路由 t2v
        assert chosen in cap["candidates"]
    finally:
        live_state._reset_for_tests()


@pytest.mark.asyncio
async def test_route_i2v_excludes_t2v_only_providers():
    """mode=i2v → veo3/kling/hailuo(能力矩阵里 t2v-only)被排除。"""
    from unittest.mock import patch as _patch

    from hevi.cost import router as R
    from hevi.resilience import live_state

    live_state._reset_for_tests()
    try:
        cap = {}

        async def fake_cheapest(**kw):
            cap["candidates"] = kw["candidates"]
            return kw["candidates"][0]

        with _patch("hevi.cost.router.select_cheapest_provider", fake_cheapest):
            await R.route_video_provider(
                duration_archetype="short", audio_provider="vibevoice", mode="i2v"
            )
        for p in ("veo3", "kling_v2", "hailuo"):
            assert p not in cap["candidates"]
        assert "wan_local" in cap["candidates"]  # i2v 可
    finally:
        live_state._reset_for_tests()


@pytest.mark.asyncio
async def test_route_raises_when_none_routable():
    from hevi.cost import router as R
    from hevi.resilience import live_state
    from hevi.video.capability_guard import PROVIDER_LIMITS

    live_state._reset_for_tests()
    try:
        for p, lim in PROVIDER_LIMITS.items():
            if "t2v" in lim.modes:
                for _ in range(live_state._WINDOW):
                    live_state.record_provider_outcome(p, is_403=True)
        with pytest.raises(ValueError):
            await R.route_video_provider(
                duration_archetype="short", audio_provider="vibevoice", mode="t2v"
            )
    finally:
        live_state._reset_for_tests()


# ── lip-sync 作为可路由能力(HEVI 路线图 Phase3 #42)──────────────────────────


@pytest.mark.asyncio
async def test_route_require_lip_sync_narrows_to_native_providers():
    """require_lip_sync=True → 只剩能力矩阵里标了 lip_sync=True 的 provider(现在
    只有 veo3——hevi 里没有 lip-sync 后处理实现,不该假装能路由到别的)。"""
    from unittest.mock import patch as _patch

    from hevi.cost import router as R
    from hevi.resilience import live_state

    live_state._reset_for_tests()
    try:
        cap = {}

        async def fake_cheapest(**kw):
            cap["candidates"] = kw["candidates"]
            return kw["candidates"][0]

        with _patch("hevi.cost.router.select_cheapest_provider", fake_cheapest):
            chosen = await R.route_video_provider(
                duration_archetype="short",
                audio_provider="vibevoice",
                mode="t2v",
                require_lip_sync=True,
            )
        assert cap["candidates"] == ["veo3"]
        assert chosen == "veo3"
    finally:
        live_state._reset_for_tests()


@pytest.mark.asyncio
async def test_route_require_lip_sync_raises_when_native_provider_unroutable():
    from hevi.cost import router as R
    from hevi.resilience import live_state

    live_state._reset_for_tests()
    try:
        for _ in range(live_state._WINDOW):
            live_state.record_provider_outcome("veo3", is_403=True)
        with pytest.raises(ValueError, match="lip_sync"):
            await R.route_video_provider(
                duration_archetype="short",
                audio_provider="vibevoice",
                mode="t2v",
                require_lip_sync=True,
            )
    finally:
        live_state._reset_for_tests()


@pytest.mark.asyncio
async def test_route_without_require_lip_sync_unaffected():
    """不要求 lip_sync 时行为完全不变(向后兼容)。"""
    from unittest.mock import patch as _patch

    from hevi.cost import router as R
    from hevi.resilience import live_state

    live_state._reset_for_tests()
    try:
        cap = {}

        async def fake_cheapest(**kw):
            cap["candidates"] = kw["candidates"]
            return kw["candidates"][0]

        with _patch("hevi.cost.router.select_cheapest_provider", fake_cheapest):
            await R.route_video_provider(
                duration_archetype="short", audio_provider="vibevoice", mode="t2v"
            )
        assert "wan_local" in cap["candidates"]  # 没被 lip_sync 过滤掉
    finally:
        live_state._reset_for_tests()


def test_shot_router_classify_quality_floor():
    """route v2:镜头 prompt → 质量下限。空镜降档(可用免费本地),主角特写抬档(只上云)。"""
    from hevi.cost.shot_router import classify_shot_quality_floor

    assert classify_shot_quality_floor("空镜 城市天际线 establishing shot") == 7
    assert classify_shot_quality_floor("主角特写,close-up on hero's face") == 10
    assert classify_shot_quality_floor("两人走在街上") == 9  # 无关键词 → 默认
    assert classify_shot_quality_floor("", default=8) == 8


@pytest.mark.asyncio
async def test_shot_router_propagates_floor_to_route():
    """route_shot_provider 把分类得到的 floor 透传给 route_video_provider。"""
    from unittest.mock import patch as _patch

    from hevi.cost import shot_router as SR

    seen: dict[str, Any] = {}

    async def fake_route(**kw):
        seen.update(kw)
        return "wan_local"

    with _patch("hevi.cost.shot_router.route_video_provider", fake_route):
        # 空镜 → floor 7
        await SR.route_shot_provider(
            prompt="空镜 远景 landscape",
            duration_archetype="short",
            audio_provider="vibevoice",
            mode="t2v",
        )
        assert seen["quality_floor"] == 7
        # 主角特写 → floor 10
        await SR.route_shot_provider(
            prompt="主角特写 portrait",
            duration_archetype="short",
            audio_provider="vibevoice",
            mode="i2v",
        )
        assert seen["quality_floor"] == 10
        assert seen["mode"] == "i2v"


@pytest.mark.asyncio
async def test_shot_router_propagates_require_lip_sync():
    from unittest.mock import patch as _patch

    from hevi.cost import shot_router as SR

    seen: dict[str, Any] = {}

    async def fake_route(**kw):
        seen.update(kw)
        return "veo3"

    with _patch("hevi.cost.shot_router.route_video_provider", fake_route):
        await SR.route_shot_provider(
            prompt="主角对白特写",
            duration_archetype="short",
            audio_provider="vibevoice",
            require_lip_sync=True,
        )
    assert seen["require_lip_sync"] is True
