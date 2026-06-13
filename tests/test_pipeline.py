from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from omodul.agentic_longvideo_pipeline import LongVideoConfig, LongVideoResult

from hevi.pipeline.config_builder import build_longvideo_config
from hevi.pipeline.longvideo_orchestrator import orchestrate_longvideo
from hevi.pipeline.result_mapper import map_longvideo_result
from hevi.providers.registry import ProviderRegistry, register_all_providers


@pytest.fixture
def mock_lv_result():
    return LongVideoResult(
        video_path=Path("output/test_video.mp4"),
        duration_s=120.5,
        chapters=3,
        shots_generated=15,
        provider_used={"video": "ltx2_cloud", "audio": "vibevoice"},
    )


@pytest.mark.asyncio
async def test_orchestrate_longvideo_basic(mock_lv_result):
    with patch(
        "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline", new_callable=AsyncMock
    ) as mock_pipeline:
        mock_pipeline.return_value = mock_lv_result
        res = await orchestrate_longvideo(
            topic="Space Exploration",
            duration_archetype="1-5min",
            video_provider="ltx2_cloud",
            audio_provider="vibevoice",
        )
        assert res["id"] == "hevi_test_video"
        assert res["duration"] == 120.5
        assert res["metadata"]["chapters"] == 3

        mock_pipeline.assert_called_once()
        config = mock_pipeline.call_args.kwargs["config"]
        assert isinstance(config, LongVideoConfig)
        assert config.topic == "Space Exploration"
        assert config.duration_archetype == "1-5min"


@pytest.mark.asyncio
async def test_orchestrate_multi_character(mock_lv_result):
    with patch(
        "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline", new_callable=AsyncMock
    ) as mock_pipeline:
        mock_pipeline.return_value = mock_lv_result
        await orchestrate_longvideo(
            topic="Teamwork",
            duration_archetype="5-15min",
            video_provider="wan_cloud",
            audio_provider="duix",
            num_characters=4,
        )
        config = mock_pipeline.call_args.kwargs["config"]
        assert config.num_characters == 4
        assert config.video_provider == "wan_cloud"
        assert config.audio_provider == "duix"


@pytest.mark.parametrize("archetype", ["1-5min", "5-15min", "15-45min", "45min+"])
def test_config_builder_archetypes(archetype):
    config = build_longvideo_config(
        topic="test",
        duration_archetype=archetype,
        video_provider="ltx2_cloud",
        audio_provider="vibevoice",
    )
    assert config.duration_archetype == archetype


def test_config_builder_invalid_archetype():
    with pytest.raises(ValueError, match="Unknown duration archetype"):
        build_longvideo_config(
            topic="test",
            duration_archetype="invalid",
            video_provider="ltx2_cloud",
            audio_provider="vibevoice",
        )


def test_config_builder_invalid_video_provider():
    with pytest.raises(ValueError, match="Invalid video provider"):
        build_longvideo_config(
            topic="test",
            duration_archetype="1-5min",
            video_provider="invalid_provider",
            audio_provider="vibevoice",
        )


def test_config_builder_invalid_audio_provider():
    with pytest.raises(ValueError, match="Invalid audio provider"):
        build_longvideo_config(
            topic="test",
            duration_archetype="1-5min",
            video_provider="ltx2_cloud",
            audio_provider="invalid_provider",
        )


def test_result_mapper(mock_lv_result):
    mapped = map_longvideo_result(mock_lv_result)
    assert mapped["id"] == "hevi_test_video"
    assert mapped["url"] == "output/test_video.mp4"
    assert mapped["duration"] == 120.5
    assert mapped["metadata"]["shots"] == 15
    assert mapped["metadata"]["providers"]["video"] == "ltx2_cloud"


def test_register_all_providers_full():
    ProviderRegistry._providers = {}
    register_all_providers()

    assert ("video", "ltx2_cloud") in ProviderRegistry._providers
    assert ("video", "wan_cloud") in ProviderRegistry._providers
    assert ("audio", "vibevoice") in ProviderRegistry._providers
    assert ("audio", "duix") in ProviderRegistry._providers


@pytest.mark.asyncio
async def test_orchestrate_longvideo_style_lang(mock_lv_result):
    with patch(
        "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline", new_callable=AsyncMock
    ) as mock_pipeline:
        mock_pipeline.return_value = mock_lv_result
        await orchestrate_longvideo(
            topic="Cyberpunk",
            duration_archetype="1-5min",
            video_provider="ltx2_cloud",
            audio_provider="vibevoice",
            style="anime",
            language="en",
        )
        config = mock_pipeline.call_args.kwargs["config"]
        assert config.style == "anime"
        assert config.language == "en"


@pytest.mark.asyncio
async def test_orchestrate_15_45min(mock_lv_result):
    with patch(
        "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline", new_callable=AsyncMock
    ) as mock_pipeline:
        mock_pipeline.return_value = mock_lv_result
        await orchestrate_longvideo(
            topic="Epic Saga",
            duration_archetype="15-45min",
            video_provider="ltx2_cloud",
            audio_provider="vibevoice",
        )
        config = mock_pipeline.call_args.kwargs["config"]
        assert config.duration_archetype == "15-45min"


@pytest.mark.asyncio
async def test_orchestrate_45min_plus(mock_lv_result):
    with patch(
        "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline", new_callable=AsyncMock
    ) as mock_pipeline:
        mock_pipeline.return_value = mock_lv_result
        await orchestrate_longvideo(
            topic="Documentary",
            duration_archetype="45min+",
            video_provider="ltx2_cloud",
            audio_provider="vibevoice",
        )
        config = mock_pipeline.call_args.kwargs["config"]
        assert config.duration_archetype == "45min+"


@pytest.mark.asyncio
async def test_orchestrate_with_fallback(mock_lv_result):
    with patch(
        "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline", new_callable=AsyncMock
    ) as mock_pipeline:
        mock_pipeline.return_value = mock_lv_result
        await orchestrate_longvideo(
            topic="test",
            duration_archetype="1-5min",
            video_provider="ltx2_cloud",
            audio_provider="vibevoice",
            fallback_video_provider="wan_cloud",
        )
        config = mock_pipeline.call_args.kwargs["config"]
        assert config.fallback_video_provider == "wan_cloud"
