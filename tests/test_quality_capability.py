"""P10.F2 tests — quality profiles, capability guard, health-check fallback, cost coupling."""

from unittest.mock import AsyncMock, patch

import pytest

from hevi.video.capability_guard import CapabilityError, validate_request
from hevi.video.kernel_service import generate_clip
from hevi.video.quality_profile import (
    QUALITY_PROFILES,
    QualityProfile,
    get_quality_cost_multiplier,
    get_quality_profile,
)

# ── 1. Quality profile definitions ───────────────────────────────────────────

def test_quality_profiles_exist():
    assert set(QUALITY_PROFILES) == {"standard", "high", "ultra"}


def test_quality_profile_standard():
    p = QUALITY_PROFILES["standard"]
    assert p.resolution == (720, 1280)
    assert p.fps == 24
    assert p.bitrate_kbps == 2500


def test_quality_profile_high():
    p = QUALITY_PROFILES["high"]
    assert p.resolution == (1080, 1920)
    assert p.fps == 30
    assert p.bitrate_kbps == 5000


def test_quality_profile_ultra():
    p = QUALITY_PROFILES["ultra"]
    assert p.resolution == (2160, 3840)
    assert p.fps == 30
    assert p.bitrate_kbps == 12000


def test_get_quality_profile_returns_correct_type():
    for name in ("standard", "high", "ultra"):
        assert isinstance(get_quality_profile(name), QualityProfile)


def test_get_quality_profile_default():
    p = get_quality_profile()
    assert p == QUALITY_PROFILES["standard"]


def test_get_quality_profile_unknown_raises():
    with pytest.raises(ValueError, match="Unknown quality profile"):
        get_quality_profile("4k_hdr")


# ── 2. generate_clip quality param transparently passes fps/bitrate ───────────

@pytest.mark.asyncio
async def test_generate_clip_standard_fps_bitrate(tmp_path):
    out = tmp_path / "o.mp4"
    with patch("hevi.video.kernel_service.ltx2_cloud_generate", new_callable=AsyncMock) as m:
        m.return_value = out
        await generate_clip(
            config={}, provider="ltx2_cloud", mode="t2v",
            prompt="x", duration_s=5.0, output_path=out, quality="standard",
        )
        kw = m.call_args.kwargs
        assert kw["fps"] == 24
        assert kw["bitrate_kbps"] == 2500


@pytest.mark.asyncio
async def test_generate_clip_ultra_fps_bitrate(tmp_path):
    out = tmp_path / "o.mp4"
    with patch("hevi.video.kernel_service.ltx2_cloud_generate", new_callable=AsyncMock) as m:
        m.return_value = out
        await generate_clip(
            config={}, provider="ltx2_cloud", mode="t2v",
            prompt="x", duration_s=5.0, output_path=out, quality="ultra",
        )
        kw = m.call_args.kwargs
        assert kw["fps"] == 30
        assert kw["bitrate_kbps"] == 12000


@pytest.mark.asyncio
async def test_generate_clip_default_quality_is_standard(tmp_path):
    out = tmp_path / "o.mp4"
    with patch("hevi.video.kernel_service.ltx2_cloud_generate", new_callable=AsyncMock) as m:
        m.return_value = out
        await generate_clip(
            config={}, provider="ltx2_cloud", mode="t2v",
            prompt="x", duration_s=5.0, output_path=out,
        )
        kw = m.call_args.kwargs
        assert kw["fps"] == 24
        assert kw["bitrate_kbps"] == 2500


@pytest.mark.asyncio
async def test_generate_clip_wan_passes_quality_params(tmp_path):
    out = tmp_path / "o.mp4"
    with patch("hevi.video.kernel_service.video_generate", new_callable=AsyncMock) as m:
        m.return_value = out
        await generate_clip(
            config={}, provider="wan_cloud", mode="t2v",
            prompt="x", duration_s=5.0, output_path=out, quality="high",
        )
        kw = m.call_args.kwargs
        assert kw["fps"] == 30
        assert kw["bitrate_kbps"] == 5000


# ── 3. Capability guard — valid requests pass ─────────────────────────────────

@pytest.mark.asyncio
async def test_validate_request_ltx2_valid():
    await validate_request(
        provider="ltx2_cloud", mode="t2v",
        resolution=(1080, 1920), duration_s=60.0, fps=24,
    )


@pytest.mark.asyncio
async def test_validate_request_wan_valid():
    await validate_request(
        provider="wan_cloud", mode="i2v",
        resolution=(720, 1280), duration_s=30.0, fps=24,
    )


# ── 4. Capability guard — violations raise CapabilityError ───────────────────

@pytest.mark.asyncio
async def test_validate_unknown_provider_raises():
    with pytest.raises(CapabilityError, match="Unknown provider"):
        await validate_request(
            provider="bogus_cloud", mode="t2v",
            resolution=(720, 1280), duration_s=10.0, fps=24,
        )


@pytest.mark.asyncio
async def test_validate_resolution_exceeds_max_raises():
    with pytest.raises(CapabilityError, match="Resolution"):
        await validate_request(
            provider="wan_cloud", mode="t2v",
            resolution=(4096, 4096), duration_s=10.0, fps=24,
        )


@pytest.mark.asyncio
async def test_validate_duration_exceeds_max_raises():
    with pytest.raises(CapabilityError, match="Duration"):
        await validate_request(
            provider="wan_cloud", mode="t2v",
            resolution=(720, 1280), duration_s=999.0, fps=24,
        )


@pytest.mark.asyncio
async def test_validate_fps_not_in_options_raises():
    with pytest.raises(CapabilityError, match="fps="):
        await validate_request(
            provider="wan_cloud", mode="t2v",
            resolution=(720, 1280), duration_s=10.0, fps=60,
        )


@pytest.mark.asyncio
async def test_validate_mode_unsupported_via_obase_caps():
    """When obase registers a provider with limited caps, unsupported mode is caught."""
    from obase.provider_registry import ProviderRegistry
    ProviderRegistry.register_with_capability(
        "video", "ltx2_cloud", lambda: None,
        capabilities=["t2v"],  # only t2v registered
        replace=True,
    )
    try:
        with pytest.raises(CapabilityError, match="do not include mode"):
            await validate_request(
                provider="ltx2_cloud", mode="i2v",
                resolution=(720, 1280), duration_s=10.0, fps=24,
            )
    finally:
        ProviderRegistry.clear()


# ── 5. Capability guard — obase capabilities() is consulted ──────────────────

@pytest.mark.asyncio
async def test_capabilities_called_for_mode_check():
    """validate_request calls ProviderRegistry.capabilities."""
    with patch("hevi.video.capability_guard.ProviderRegistry") as mock_reg:
        mock_reg.capabilities.return_value = []  # not registered → use PROVIDER_LIMITS
        await validate_request(
            provider="ltx2_cloud", mode="t2v",
            resolution=(720, 1280), duration_s=10.0, fps=24,
        )
        mock_reg.capabilities.assert_called_once_with("video", "ltx2_cloud")


# ── 6. Health-check before fallback ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_fallback_skips_unhealthy_provider():
    """When the second provider fails health check it is skipped."""
    runner = AsyncMock(side_effect=ValueError("p1 down"))
    on_fallback = AsyncMock()

    hc_patch = patch(
        "hevi.resilience.fallback_chain.provider_health_check", new_callable=AsyncMock
    )
    sleep_patch = patch("hevi.resilience.retry_policy.asyncio.sleep", new_callable=AsyncMock)
    with hc_patch as mock_hc, sleep_patch:
        mock_hc.return_value = False  # second provider unhealthy
        # last_exc from first provider is re-raised when all candidates exhausted
        with pytest.raises(ValueError, match="p1 down"):
            from hevi.resilience import run_with_fallback
            await run_with_fallback(
                initial_provider="ltx2_cloud",
                runner=runner,
                on_fallback=on_fallback,
            )
        mock_hc.assert_called_once_with("wan_cloud")
        on_fallback.assert_not_called()


@pytest.mark.asyncio
async def test_fallback_uses_healthy_provider():
    """When second provider passes health check, runner is called for it."""
    runner = AsyncMock(side_effect=[ValueError("p1 down"), "ok"])
    on_fallback = AsyncMock()

    hc_patch = patch(
        "hevi.resilience.fallback_chain.provider_health_check", new_callable=AsyncMock
    )
    sleep_patch = patch("hevi.resilience.retry_policy.asyncio.sleep", new_callable=AsyncMock)
    with hc_patch as mock_hc, sleep_patch:
        mock_hc.return_value = True  # second provider healthy
        from hevi.resilience import run_with_fallback
        result = await run_with_fallback(
            initial_provider="ltx2_cloud",
            runner=runner,
            on_fallback=on_fallback,
        )
        assert result == "ok"
        mock_hc.assert_called_once_with("wan_cloud")


@pytest.mark.asyncio
async def test_health_check_not_called_for_first_provider():
    """Initial provider is always attempted without a health probe."""
    runner = AsyncMock(return_value="done")
    on_fallback = AsyncMock()

    with patch(
        "hevi.resilience.fallback_chain.provider_health_check", new_callable=AsyncMock
    ) as mock_hc:
        from hevi.resilience import run_with_fallback
        await run_with_fallback(
            initial_provider="ltx2_cloud",
            runner=runner,
            on_fallback=on_fallback,
        )
        mock_hc.assert_not_called()


# ── 7. Cost coupling — ultra costs more than standard ────────────────────────

def test_quality_cost_multiplier_ordering():
    assert get_quality_cost_multiplier("standard") < get_quality_cost_multiplier("high")
    assert get_quality_cost_multiplier("high") < get_quality_cost_multiplier("ultra")


@pytest.mark.asyncio
async def test_estimate_cost_ultra_gt_standard():
    from hevi.cost import estimate_cost

    std = await estimate_cost(
        duration_archetype="1-5min",
        video_provider="ltx2_cloud",
        audio_provider="vibevoice",
        quality="standard",
    )
    ultra = await estimate_cost(
        duration_archetype="1-5min",
        video_provider="ltx2_cloud",
        audio_provider="vibevoice",
        quality="ultra",
    )
    assert ultra.total_usd > std.total_usd
    assert ultra.breakdown["quality"] == "ultra"
