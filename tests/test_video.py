from unittest.mock import AsyncMock, patch

import pytest

from hevi.providers.registry import ProviderRegistry, register_all_providers
from hevi.video.duration_mapper import DURATION_ARCHETYPES, get_duration_config
from hevi.video.kernel_service import generate_clip
from hevi.video.provider_config import VideoProvider
from hevi.video.wan_local_service import wan_local_generate


@pytest.fixture
def mock_config():
    return {"api_key": "test_key"}


@pytest.fixture
def output_path(tmp_path):
    return tmp_path / "output.mp4"


@pytest.fixture
def reference_image(tmp_path):
    img = tmp_path / "ref.png"
    img.write_text("dummy")
    return img


@pytest.mark.asyncio
async def test_generate_clip_ltx2_t2v(mock_config, output_path):
    with patch(
        "hevi.video.kernel_service.ltx2_cloud_generate", new_callable=AsyncMock
    ) as mock_ltx2:
        mock_ltx2.return_value = output_path
        res = await generate_clip(
            config=mock_config,
            provider="ltx2_cloud",
            mode="t2v",
            prompt="A sunset",
            duration_s=5.0,
            resolution=(1280, 720),
            audio_enabled=True,
            output_path=output_path,
        )
        assert res == output_path
        expected_config = {**mock_config, "FAL_BASE_URL": "https://fal.run/fal-ai/ltx-video"}
        mock_ltx2.assert_called_once_with(
            config=expected_config,
            mode="t2v",
            prompt="A sunset",
            reference_image=None,
            duration_s=5.0,
            resolution=(1280, 720),
            audio_enabled=True,
            output_path=output_path,
            fps=24,
            bitrate_kbps=2500,
        )


@pytest.mark.asyncio
async def test_generate_clip_ltx2_i2v(mock_config, output_path, reference_image):
    with patch(
        "hevi.video.kernel_service.ltx2_cloud_generate", new_callable=AsyncMock
    ) as mock_ltx2:
        mock_ltx2.return_value = output_path
        res = await generate_clip(
            config=mock_config,
            provider=VideoProvider.LTX2_CLOUD,
            mode="i2v",
            prompt="A sunset",
            reference_image=reference_image,
            duration_s=5.0,
            output_path=output_path,
        )
        assert res == output_path
        expected_config = {**mock_config, "FAL_BASE_URL": "https://fal.run/fal-ai/ltx-video"}
        mock_ltx2.assert_called_once_with(
            config=expected_config,
            mode="i2v",
            prompt="A sunset",
            reference_image=reference_image,
            duration_s=5.0,
            resolution=(1280, 720),
            audio_enabled=True,
            output_path=output_path,
            fps=24,
            bitrate_kbps=2500,
        )


@pytest.mark.asyncio
async def test_generate_clip_wan_t2v(mock_config, output_path):
    with patch("hevi.video.kernel_service.video_generate", new_callable=AsyncMock) as mock_wan:
        mock_wan.return_value = output_path
        res = await generate_clip(
            config=mock_config,
            provider="wan_cloud",
            mode="t2v",
            prompt="A forest",
            duration_s=10.0,
            output_path=output_path,
        )
        assert res == output_path
        mock_wan.assert_called_once_with(
            config=mock_config,
            provider="wan_cloud",
            mode="t2v",
            prompt="A forest",
            reference_image=None,
            duration_s=10.0,
            output_path=output_path,
            fps=24,
            bitrate_kbps=2500,
        )


@pytest.mark.asyncio
async def test_generate_clip_wan_i2v(mock_config, output_path, reference_image):
    with patch("hevi.video.kernel_service.video_generate", new_callable=AsyncMock) as mock_wan:
        mock_wan.return_value = output_path
        res = await generate_clip(
            config=mock_config,
            provider=VideoProvider.WAN_CLOUD,
            mode="i2v",
            prompt="A forest",
            reference_image=reference_image,
            duration_s=10.0,
            output_path=output_path,
        )
        assert res == output_path
        mock_wan.assert_called_once_with(
            config=mock_config,
            provider="wan_cloud",
            mode="i2v",
            prompt="A forest",
            reference_image=reference_image,
            duration_s=10.0,
            output_path=output_path,
            fps=24,
            bitrate_kbps=2500,
        )


@pytest.mark.asyncio
async def test_generate_clip_audio_disabled(mock_config, output_path):
    with patch(
        "hevi.video.kernel_service.ltx2_cloud_generate", new_callable=AsyncMock
    ) as mock_ltx2:
        mock_ltx2.return_value = output_path
        await generate_clip(
            config=mock_config,
            provider="ltx2_cloud",
            mode="t2v",
            prompt="test",
            duration_s=5.0,
            audio_enabled=False,
            output_path=output_path,
        )
        assert mock_ltx2.call_args.kwargs["audio_enabled"] is False


@pytest.mark.asyncio
async def test_generate_clip_unknown_provider(mock_config, output_path):
    with pytest.raises(ValueError, match="Unknown video provider"):
        await generate_clip(
            config=mock_config,
            provider="unknown_provider",
            mode="t2v",
            prompt="test",
            duration_s=5.0,
            output_path=output_path,
        )


@pytest.mark.asyncio
async def test_generate_clip_invalid_mode(mock_config, output_path):
    with pytest.raises(ValueError, match="Invalid mode"):
        await generate_clip(
            config=mock_config,
            provider="ltx2_cloud",
            mode="invalid_mode",  # type: ignore
            prompt="test",
            duration_s=5.0,
            output_path=output_path,
        )


@pytest.mark.parametrize(
    "archetype,expected",
    [
        ("1-5min", {"target_s": 180, "clip_s": 20, "max_clips": 15}),
        ("5-15min", {"target_s": 600, "clip_s": 20, "max_clips": 45}),
        ("15-45min", {"target_s": 1800, "clip_s": 20, "max_clips": 135}),
        ("45min+", {"target_s": 3600, "clip_s": 20, "max_clips": 270}),
    ],
)
def test_duration_mapper_archetypes(archetype, expected):
    assert get_duration_config(archetype) == expected


def test_duration_mapper_unknown():
    with pytest.raises(ValueError, match="Unknown duration archetype"):
        get_duration_config("invalid")


@pytest.mark.asyncio
async def test_generate_clip_wan_local(mock_config, output_path):
    with patch("hevi.video.kernel_service.wan_local_generate", new_callable=AsyncMock) as mock_wl:
        mock_wl.return_value = output_path
        res = await generate_clip(
            config=mock_config,
            provider="wan_local",
            mode="t2v",
            prompt="A mountain scene",
            duration_s=5.0,
            output_path=output_path,
        )
        assert res == output_path
        mock_wl.assert_called_once_with(prompt="A mountain scene", output_path=output_path)


@pytest.mark.asyncio
async def test_wan_local_generate_calls_provider(tmp_path):
    out = tmp_path / "clip.mp4"
    with (
        patch("hevi.video.wan_local_service.wan_local_provider") as mock_provider,
        patch("hevi.video.wan_local_service.scheduler") as mock_sched,
    ):
        mock_provider.is_loaded.return_value = True
        mock_provider.get_model.return_value.generate.return_value = None
        mock_sched.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_sched.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        import unittest.mock
        with unittest.mock.patch("hevi.video.wan_local_service.asyncio.get_running_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(return_value=None)
            result = await wan_local_generate(prompt="test", output_path=out)

        assert result == out


def test_register_all_providers():
    ProviderRegistry.clear()

    with patch("hevi.providers.registry.ltx2_cloud_generate"), patch(
        "hevi.providers.registry.video_generate"
    ):
        register_all_providers()

        assert ProviderRegistry.has("video", "ltx2_cloud")
        assert ProviderRegistry.has("video", "wan_cloud")
        assert ProviderRegistry.has("video", "wan_local")


def test_video_provider_enum():
    assert VideoProvider.LTX2_CLOUD == "ltx2_cloud"
    assert VideoProvider.WAN_CLOUD == "wan_cloud"
    assert VideoProvider.WAN_LOCAL == "wan_local"


@pytest.mark.asyncio
async def test_generate_clip_wan_cloud_no_audio_res_args(mock_config, output_path):
    """Verify wan_cloud doesn't receive resolution/audio_enabled as per snippet."""
    with patch("hevi.video.kernel_service.video_generate", new_callable=AsyncMock) as mock_wan:
        mock_wan.return_value = output_path
        await generate_clip(
            config=mock_config,
            provider="wan_cloud",
            mode="t2v",
            prompt="test",
            duration_s=5.0,
            resolution=(1920, 1080),
            audio_enabled=True,
            output_path=output_path,
        )
        kwargs = mock_wan.call_args.kwargs
        assert "resolution" not in kwargs
        assert "audio_enabled" not in kwargs
        assert kwargs["provider"] == "wan_cloud"


def test_duration_archetypes_constant():
    assert "1-5min" in DURATION_ARCHETYPES
    assert "5-15min" in DURATION_ARCHETYPES
    assert "15-45min" in DURATION_ARCHETYPES
    assert "45min+" in DURATION_ARCHETYPES
