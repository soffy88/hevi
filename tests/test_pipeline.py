from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from omodul.agentic_longvideo_pipeline import LongVideoConfig, LongVideoResult

from hevi.pipeline.config_builder import build_longvideo_config
from hevi.pipeline.longvideo_orchestrator import (
    _order_and_dedup_shots,
    orchestrate_longvideo,
)
from hevi.pipeline.result_mapper import map_longvideo_result
from hevi.providers.registry import ProviderRegistry, register_all_providers


def test_order_and_dedup_shots(tmp_path):
    """RFC-001 P0-2: 按镜头序号排序 + 每序号只留最大(选中)变体。"""

    def _mk(name: str, size: int) -> Path:
        p = tmp_path / name
        p.write_bytes(b"\x00" * size)
        return p

    # 乱序输入;index 1 有两个变体(v1 更大 → 选中)
    s2 = _mk("shot_0002_v0.mp4", 100)
    s0 = _mk("shot_0000_v0.mp4", 100)
    _s1v0 = _mk("shot_0001_v0.mp4", 50)
    s1v1 = _mk("shot_0001_v1.mp4", 200)

    out = _order_and_dedup_shots([s2, s0, _s1v0, s1v1])
    assert out == [s0, s1v1, s2]  # 有序 + index1 去重保留更大的 v1


def test_order_and_dedup_shots_unparsed_appended(tmp_path):
    a = tmp_path / "shot_0000_v0.mp4"
    a.write_bytes(b"\x00" * 10)
    z = tmp_path / "intro.mp4"
    z.write_bytes(b"\x00" * 10)
    out = _order_and_dedup_shots([z, a])
    assert out == [a, z]  # 可解析的在前(按序号),不可解析的按名追加


@pytest.fixture(autouse=True)
def _register_providers():
    """orchestrate_longvideo looks up the 'default' LLM from the global registry.
    Register providers so these tests don't depend on another test file having
    populated the process-wide ProviderRegistry singleton first."""
    register_all_providers()
    yield


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
    assert mapped["shots"] == []  # 无 shots(老 omodul) → 空列表


def test_result_mapper_exposes_shot_records():
    """C3: result_mapper 把 omodul v1.36.0 的 per-shot 明细透出(Path→str,供 ShotState 落库)。"""
    from omodul.agentic_longvideo_pipeline import LongVideoResult, ShotRecord

    r = LongVideoResult(
        video_path=Path("output/v.mp4"),
        duration_s=5.0,
        chapters=1,
        shots_generated=2,
        provider_used={"video": "wan_local", "audio": "vibevoice"},
        shots=[
            ShotRecord(
                index=0,
                path=Path("s0_v1.mp4"),
                provider="wan_local",
                variant_chosen=1,
                consistency_score=0.94,
                passed=True,
            ),
            ShotRecord(
                index=1,
                path=Path("s1_v0.mp4"),
                provider="wan_local",
                variant_chosen=0,
                consistency_score=0.88,
                passed=True,
            ),
        ],
    )
    mapped = map_longvideo_result(r)
    assert len(mapped["shots"]) == 2
    s0 = mapped["shots"][0]
    assert s0["index"] == 0 and s0["variant_chosen"] == 1
    assert s0["consistency_score"] == 0.94
    assert isinstance(s0["path"], str)  # mode="json" → 可直接落 JSONB


@pytest.mark.asyncio
async def test_orchestrate_regenerate_dispatches_to_omodul(mock_lv_result):
    """C3 verdict→返工:regenerate_shot_ids 设置 → 走 omodul.regenerate_shots(非整片重跑)。"""
    register_all_providers()  # 确保 default llm 等已注册(standalone 安全)
    with (
        patch(
            "omodul.agentic_longvideo_pipeline.regenerate_shots", new_callable=AsyncMock
        ) as mock_regen,
        patch(
            "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline",
            new_callable=AsyncMock,
        ) as mock_full,
    ):
        mock_regen.return_value = mock_lv_result
        res = await orchestrate_longvideo(
            topic="t",
            duration_archetype="1-5min",
            video_provider="ltx2_cloud",
            audio_provider="vibevoice",
            regenerate_shot_ids=[1],
            shot_hints={1: "brighter lighting"},
        )
        mock_regen.assert_awaited_once()
        mock_full.assert_not_awaited()  # 没走整片生成
        kw = mock_regen.call_args.kwargs
        assert kw["shot_ids"] == [1]
        assert kw["hints"] == {1: "brighter lighting"}
        assert res["id"] == "hevi_test_video"


def test_register_all_providers_full():
    ProviderRegistry.clear()
    register_all_providers()

    assert ProviderRegistry.has("video", "ltx2_cloud")
    assert ProviderRegistry.has("video", "wan_cloud")
    assert ProviderRegistry.has("audio", "vibevoice")
    assert ProviderRegistry.has("audio", "duix")


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
