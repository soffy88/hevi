from unittest.mock import AsyncMock, patch

import pytest

from hevi.providers.registry import ProviderRegistry, register_all_providers
from hevi.video.duration_mapper import DURATION_ARCHETYPES, get_duration_config
from hevi.video.kernel_service import generate_clip
from hevi.video.provider_config import VideoProvider


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
        mock_ltx2.assert_called_once_with(
            config=mock_config,
            mode="t2v",
            prompt="A sunset",
            reference_image=None,
            duration_s=5.0,
            resolution=(1280, 720),
            audio_enabled=True,
            output_path=output_path,
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
        mock_ltx2.assert_called_once_with(
            config=mock_config,
            mode="i2v",
            prompt="A sunset",
            reference_image=reference_image,
            duration_s=5.0,
            resolution=(1280, 720),
            audio_enabled=True,
            output_path=output_path,
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


def test_register_all_providers():
    # Clear registry for clean test
    ProviderRegistry._providers = {}

    with patch("hevi.providers.registry.ltx2_cloud_generate"), patch(
        "hevi.providers.registry.video_generate"
    ):
        register_all_providers()

        # Verify registration
        assert ("video", "ltx2_cloud") in ProviderRegistry._providers
        assert ("video", "wan_cloud") in ProviderRegistry._providers


def test_video_provider_enum():
    assert VideoProvider.LTX2_CLOUD == "ltx2_cloud"
    assert VideoProvider.WAN_CLOUD == "wan_cloud"


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
