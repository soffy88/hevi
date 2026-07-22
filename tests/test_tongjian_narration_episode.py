"""SPEC-005 §6 第一批集成测试:EventUnit(narration 段)→ 纯讲解版成片,全链路 mock
llm/tts_fn/image_gen(零外部 API 花费),真实本地 ffmpeg 装配(同 test_tongjian_assemble.py
的 ffmpeg_only 惯例——纯本地处理,不是"真实花费"的实跑)。"""

from __future__ import annotations

import json
import shutil
import struct
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from hevi.tongjian.narration_episode import _build_constitution, build_narration_episode
from hevi.tongjian.schemas import EventUnit, Script, ScriptLine, Segment

_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
ffmpeg_only = pytest.mark.skipif(not _HAS_FFMPEG, reason="needs ffmpeg/ffprobe")


def _make_event_unit() -> EventUnit:
    return EventUnit(
        event_unit_id="EU001",
        source_ref="史记·商君列传",
        title="商鞅立木",
        era="战国·秦",
        year=-359,
        summary="商鞅立木南门,悬赏取信于民",
        segments=[
            Segment(type="narration", source_text="令既具，未布，恐民之不信，", order=0),
            Segment(type="drama", source_text="乃立三丈之木於國都市南門", order=1),
            Segment(type="narration", source_text="民怪之，莫敢徙。", order=2),
        ],
    )


def _mock_llm() -> AsyncMock:
    draft = {
        "lines": [
            {
                "text": "秦孝公任用商鞅变法，新法拟定却迟迟未公布，商鞅担心百姓不信任新法。",
                "visual_type": "scene",
                "visual_hint": "咸阳城,新法竹简",
            },
            {
                "text": "此事发生于战国中期，正是秦国变法图强的关键节点。",
                "visual_type": "timeline",
                "visual_hint": "战国秦变法时间线",
            },
        ]
    }
    llm = AsyncMock()
    llm.return_value = {"content": json.dumps(draft, ensure_ascii=False)}
    return llm


def _write_fake_wav(path: Path, duration_ms: int = 2000) -> None:
    sample_rate = 16000
    num_samples = int(sample_rate * duration_ms / 1000)
    data_size = num_samples * 2
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))
        f.write(struct.pack("<HHIIHH", 1, 1, sample_rate, sample_rate * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(b"\x00" * data_size)


def _mock_tts_fn(duration_ms: int = 3000):
    async def _tts(*, script, output_path, **kwargs):
        _write_fake_wav(output_path, duration_ms)
        return output_path

    return _tts


def _mock_image_gen() -> AsyncMock:
    async def _gen(*, prompt, output_path, seed, extra):
        from PIL import Image

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (320, 240), (80, 60, 40)).save(output_path)
        return {"output_path": str(output_path), "seed": seed}

    return AsyncMock(side_effect=_gen)


@ffmpeg_only
@pytest.mark.asyncio
async def test_build_narration_episode_end_to_end(tmp_path):
    event_unit = _make_event_unit()
    llm = _mock_llm()
    tts_fn = _mock_tts_fn(3000)
    image_gen = _mock_image_gen()
    vlm = AsyncMock(return_value={"content": '{"passes": true, "violations": []}'})

    with (
        patch("hevi.tongjian.voiceover._get_audio_duration_ms", AsyncMock(return_value=3000)),
        patch("hevi.tongjian.scene_render._score_frame", AsyncMock(return_value=(0.3, None, True))),
    ):
        final_video, result = await build_narration_episode(
            event_unit,
            llm=llm,
            tts_fn=tts_fn,
            image_gen=image_gen,
            vlm=vlm,
            output_dir=tmp_path,
        )

    assert Path(final_video.video_path).exists()
    assert final_video.duration_ms > 0
    assert result.passed

    # 两条讲解行都成功产出了帧(其中一条是 timeline,走 diagram_gen 而非 image_gen mock,
    # 但两条都不应该"开天窗")
    assert image_gen.await_count >= 1  # 至少 scene 行那一条经过了常规 image_gen


@pytest.mark.asyncio
async def test_image_gen_dispatcher_routes_diagram_marker_to_diagram_gen(tmp_path):
    """narration_episode 的分发器:prompt 命中 [DIAGRAM:timeline] → 转发 diagram_gen,
    不调用常规 image_gen。"""
    from hevi.tongjian.narration_episode import _make_image_gen_dispatcher

    event_unit = _make_event_unit()
    scene_image_gen = _mock_image_gen()
    dispatcher = _make_image_gen_dispatcher(scene_image_gen=scene_image_gen, event_unit=event_unit)

    output_path = tmp_path / "diagram.png"
    await dispatcher(
        prompt="水墨风格历史场景空镜,[DIAGRAM:timeline] 战国秦变法时间线。无人物,背景环境。",
        output_path=output_path,
        seed=1,
        extra={},
    )

    assert output_path.exists()
    scene_image_gen.assert_not_called()


@pytest.mark.asyncio
async def test_image_gen_dispatcher_routes_plain_prompt_to_scene_image_gen(tmp_path):
    from hevi.tongjian.narration_episode import _make_image_gen_dispatcher

    event_unit = _make_event_unit()
    scene_image_gen = _mock_image_gen()
    dispatcher = _make_image_gen_dispatcher(scene_image_gen=scene_image_gen, event_unit=event_unit)

    output_path = tmp_path / "scene.png"
    await dispatcher(
        prompt="水墨风格历史场景空镜,咸阳城,新法竹简。无人物,背景环境。",
        output_path=output_path,
        seed=1,
        extra={},
    )

    scene_image_gen.assert_awaited_once()


def test_build_constitution_prefers_actual_script_length_over_raw_segment_estimate():
    """2026-07-18 真机验证实测到的真 bug:原文 segment 很短(如"卒下令"4字)但
    narration_script 允许意译展开(§1.2),生成稿常常远长于原文估算。target_duration
    若以原文估算为准,会把目标定成 1 秒,跟真实几十秒的配音一比直接判超差 4599%。"""
    event_unit = EventUnit(
        event_unit_id="EU001",
        segments=[Segment(type="narration", source_text="卒下令。", est_duration_s=1, order=0)],
    )
    script = Script(
        lines=[ScriptLine(line_id="LN001", type="narration", speaker="NARRATOR", text="秦" * 300)]
    )
    constitution = _build_constitution(event_unit, script)
    # 300 字讲解稿 ≈ 300 / 4.5 / 0.85 ≈ 78s,不应被 1s 的原文估算顶掉
    assert constitution.target_duration_sec > 60


def test_build_constitution_falls_back_to_segment_estimate_when_script_empty():
    event_unit = EventUnit(
        event_unit_id="EU001",
        segments=[Segment(type="narration", source_text="卒下令。", est_duration_s=5, order=0)],
    )
    constitution = _build_constitution(event_unit, Script(lines=[]))
    assert constitution.target_duration_sec == 5
