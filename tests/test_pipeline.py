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
    # shot_verdict 扩展(Phase1):没传 scorecards/subject/stylepack → 全部 None,不是 0/假数据。
    assert s0["style_score"] is None
    assert s0["vlm_score"] is None
    assert s0["diagnosis_category"] is None
    assert s0["subject_id"] is None
    assert s0["style_pack_id"] is None
    assert s0["tier1_passed"] is None
    assert s0["model_version"] == "wan_local"  # 暂用 provider 名做代理


def test_result_mapper_merges_scorecard_and_version_snapshot():
    """shot_verdict 扩展(Phase1):scorecards(按 index) + subject/stylepack 版本快照
    要正确合并进每个 shot,且身份不符的镜头要能推出粗粒度诊断分类。"""
    from omodul.agentic_longvideo_pipeline import LongVideoResult, ShotRecord

    from hevi.verdict.scorecard import Scorecard

    r = LongVideoResult(
        video_path=Path("output/v.mp4"),
        duration_s=5.0,
        chapters=1,
        shots_generated=1,
        provider_used={"video": "wan_local", "audio": "vibevoice"},
        shots=[
            ShotRecord(
                index=0, path=Path("s0_v0.mp4"), provider="wan_local", consistency_score=0.1
            ),
        ],
    )
    scorecards = {
        0: Scorecard(best_frame=Path("s0_v0.mp4"), best_index=0, passed=False, identity_score=0.1)
    }
    mapped = map_longvideo_result(
        r,
        scorecards=scorecards,
        subject_id="sub-1",
        subject_version=3,
        style_pack_id="pack-1",
        style_pack_version=2,
        tier0_passed=True,
    )
    s0 = mapped["shots"][0]
    assert s0["diagnosis_category"] == "参考图角色错配"
    assert s0["subject_id"] == "sub-1"
    assert s0["subject_version"] == 3
    assert s0["style_pack_id"] == "pack-1"
    assert s0["style_pack_version"] == 2
    assert s0["tier0_passed"] is True


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


@pytest.mark.asyncio
async def test_orchestrate_attaches_quality_report(mock_lv_result):
    """§7-4:quality_report 结果透出到 result['quality'](此前算了只 log 就丢)。"""
    from types import SimpleNamespace

    register_all_providers()
    fake_rep = SimpleNamespace(
        passed=False,
        violations=["时长 3.00s 偏离预期"],
        consistency=0.72,
        stats=SimpleNamespace(duration=3.0, width=832, height=480, fps=16, has_audio=True),
        loudness_lufs=-20.0,
        subtitle_alignment_rate=0.9,
    )
    with (
        patch(
            "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline",
            new_callable=AsyncMock,
        ) as mp,
        patch("hevi.video.quality_check.quality_report", new_callable=AsyncMock) as mq,
    ):
        mp.return_value = mock_lv_result
        mq.return_value = fake_rep
        res = await orchestrate_longvideo(
            topic="t",
            duration_archetype="1-5min",
            video_provider="ltx2_cloud",
            audio_provider="vibevoice",
        )
    assert res["quality"]["passed"] is False
    assert res["quality"]["violations"] == ["时长 3.00s 偏离预期"]
    assert res["quality"]["consistency"] == 0.72
    # Tier0 补全(HEVI 路线图 Phase1):响度/字幕对齐率也透出到 result["quality"]。
    assert res["quality"]["loudness_lufs"] == -20.0
    assert res["quality"]["subtitle_alignment_rate"] == 0.9
