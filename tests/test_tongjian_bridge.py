"""hevi/season_planner/tongjian_bridge.py 测试 —— StoryGraph/EpisodePlan → 通鉴
L2-L8(cloud_avatar)渲染桥接。2026-07-12:短剧此前接的通用长视频管线没有对白能力,
产出纯旁白、镜头混乱,这个桥接改用通鉴已验证的对白+口型管线。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from hevi.season_planner import tongjian_bridge as bridge
from hevi.season_planner.schemas import EpisodePlan
from hevi.storygraph.schemas import (
    StoryCharacter,
    StoryEvent,
    StoryGraph,
    StoryMeta,
    StoryQuote,
)
from hevi.tongjian.schemas import (
    AudioSegment,
    CharacterBible,
    CharacterBibleEntry,
    FinalVideo,
    FrameManifest,
    GateResult,
    MusicPlan,
    Script,
    ScriptLine,
    Shot,
    ShotFrame,
    ShotList,
    Timeline,
)


def _story() -> StoryGraph:
    return StoryGraph(
        meta=StoryMeta(source="都市短篇·翻身", char_count=500),
        characters=[
            StoryCharacter(
                char_id="C001", name="林夏", description="冷峻干练的白领", role="protagonist"
            ),
            StoryCharacter(
                char_id="C002", name="陈默", description="沉默的发小", role="supporting"
            ),
        ],
        events=[
            StoryEvent(
                event_id="E001",
                summary="林夏被裁员",
                actors=["C001"],
                beat_type="铺垫",
                dramatic_weight=2,
            ),
            StoryEvent(
                event_id="E002",
                summary="林夏与陈默对峙",
                actors=["C001", "C002"],
                beat_type="冲突",
                dramatic_weight=5,
            ),
        ],
        quotes=[
            StoryQuote(
                quote_id="Q001",
                speaker="C002",
                original="你被开除了。",
                modern="你被开除了。",
                event_id="E002",
                emotion="平静",
            ),
        ],
    )


def _episode() -> EpisodePlan:
    return EpisodePlan(
        ep_number=1,
        title="谷底",
        event_ids=["E001", "E002"],
        characters_present=["C001", "C002"],
        target_emotion_arc="压抑→爆发",
    )


# ── 确定性字段搬运(无 LLM,零成本)──────────────────────────────────────────


def test_story_to_chapter_ir_maps_fields():
    ir = bridge.story_to_chapter_ir(_story())
    assert [c.character_id for c in ir.characters] == ["C001", "C002"]
    assert ir.characters[0].canonical_name == "林夏"
    assert [e.event_id for e in ir.events] == ["E001", "E002"]
    assert ir.events[1].dramatic_weight == 5
    assert ir.quotes[0].original == "你被开除了。"


def test_episode_to_constitution_single_act_covers_episode_events():
    c = bridge.episode_to_constitution(_episode(), target_duration_sec=120)
    assert len(c.act_structure) == 1
    assert c.act_structure[0].events == ["E001", "E002"]
    assert c.target_duration_sec == 120
    # 短剧默认竖屏,不是通鉴的 16:9
    assert c.visual_style.aspect_ratio == "9:16"


def test_character_bible_uses_storygraph_description_no_llm():
    bible = bridge.character_bible_for_episode(_episode(), _story())
    assert {c.character_id for c in bible.characters} == {"C001", "C002"}
    lin_xia = next(c for c in bible.characters if c.character_id == "C001")
    assert lin_xia.appearance == "冷峻干练的白领"


def test_character_bible_only_includes_characters_present_in_episode():
    ep = EpisodePlan(ep_number=1, title="x", event_ids=["E001"], characters_present=["C001"])
    bible = bridge.character_bible_for_episode(ep, _story())
    assert [c.character_id for c in bible.characters] == ["C001"]


def test_character_bible_fills_ref_image_from_subject_ref_paths():
    """2026-07-12 补:短剧建号阶段真的会存 Subject 参考图,但此前 CharacterBible.ref_image
    (scene_render_avatar.py 的 _canonical() 本来就设计成"优先用它")从没被填过——canonical
    像全靠文字描述现场重新生成。传入 subject_ref_paths 后必须真的落进 ref_image。"""
    bible = bridge.character_bible_for_episode(
        _episode(), _story(), subject_ref_paths={"C001": "/refs/lin_xia.png"}
    )
    lin_xia = next(c for c in bible.characters if c.character_id == "C001")
    chen_mo = next(c for c in bible.characters if c.character_id == "C002")
    assert lin_xia.ref_image == "/refs/lin_xia.png"
    assert chen_mo.ref_image is None  # 没绑定参考图的角色,退回原来的文生图行为


# ── _frame_manifest_to_shot_states:身份漂移分诊断(2026-07-12 补)────────────


def test_low_consistency_score_flags_reference_mismatch():
    """character_consistency 此前只是透传,从不影响 passed——分数低于 floor 时必须真的
    标成 REFERENCE_MISMATCH 并 passed=False,SeasonBoard 的"重新生成选中"才对得上号。"""
    manifest = FrameManifest(
        frames=[ShotFrame(shot_id="1-1", scene_id="", character_consistency=0.3, degraded=False)]
    )
    shots = bridge._frame_manifest_to_shot_states(manifest)
    assert shots[0]["passed"] is False
    assert shots[0]["diagnosis_category"] == "参考图角色错配"


def test_consistency_score_above_floor_passes():
    manifest = FrameManifest(
        frames=[ShotFrame(shot_id="1-1", scene_id="", character_consistency=0.9, degraded=False)]
    )
    shots = bridge._frame_manifest_to_shot_states(manifest)
    assert shots[0]["passed"] is True
    assert shots[0]["diagnosis_category"] is None


def test_missing_consistency_score_does_not_flag():
    """空镜/没有 lead 角色的镜头,consistency_score 本来就是 None(没有身份可评),不能
    被 floor 检查误伤成"错配"。"""
    manifest = FrameManifest(
        frames=[ShotFrame(shot_id="1-1", scene_id="", character_consistency=None, degraded=False)]
    )
    shots = bridge._frame_manifest_to_shot_states(manifest)
    assert shots[0]["passed"] is True
    assert shots[0]["diagnosis_category"] is None


def test_degraded_takes_priority_over_coincidental_low_score():
    """生成调用本身失败(degraded)比一个巧合的低分更严重,degrade_reason 不该被
    REFERENCE_MISMATCH 覆盖掉。"""
    manifest = FrameManifest(
        frames=[
            ShotFrame(
                shot_id="1-1",
                scene_id="",
                character_consistency=0.1,
                degraded=True,
                degrade_reason="avatar 生成失败: timeout",
            )
        ]
    )
    shots = bridge._frame_manifest_to_shot_states(manifest)
    assert shots[0]["passed"] is False
    assert shots[0]["diagnosis_category"] == "avatar 生成失败: timeout"


# ── render_episode 端到端(mock 掉真正花钱的通鉴 L2-L8 调用)──────────────────


def _passing_gate() -> GateResult:
    return GateResult(passed=True, coverage=1.0, errors=[], warnings=[])


@pytest.mark.asyncio
async def test_render_episode_wires_l2_to_l8_and_maps_shots(tmp_path):
    script = Script(
        lines=[ScriptLine(line_id="LN001", type="dialogue", speaker="C002", text="你被开除了。")]
    )
    timeline = Timeline(audio_segments=[AudioSegment(line_id="LN001", duration_ms=2000)])
    shotlist = ShotList(shots=[Shot(shot_id="1-1", line_ids=["LN001"], characters=["C002"])])
    frame_manifest = FrameManifest(
        frames=[
            ShotFrame(
                shot_id="1-1",
                scene_id="",
                clip_path="clip.mp4",
                character_consistency=0.8,
                degraded=False,
            )
        ]
    )
    final_video = FinalVideo(video_path=str(tmp_path / "final.mp4"))

    with (
        patch(
            "hevi.tongjian.script.build_script", AsyncMock(return_value=(script, _passing_gate()))
        ),
        patch(
            "hevi.tongjian.voiceover.build_voiceover",
            AsyncMock(return_value=(timeline, _passing_gate())),
        ),
        patch(
            "hevi.tongjian.shotlist.build_shotlist",
            AsyncMock(return_value=(shotlist, _passing_gate())),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar.build_frame_manifest_avatar",
            AsyncMock(return_value=frame_manifest),
        ),
        patch(
            "hevi.tongjian.music_plan.build_music_plan",
            AsyncMock(return_value=(MusicPlan(), _passing_gate())),
        ),
        patch(
            "hevi.tongjian.assemble.build_final_video",
            AsyncMock(return_value=(final_video, _passing_gate())),
        ),
    ):
        result = await bridge.render_episode(
            _episode(), _story(), run_dir=tmp_path, llm=AsyncMock(), tts_fn=AsyncMock()
        )

    assert result["final_video"] is final_video
    assert result["shots"] == [
        {
            "index": 0,
            "path": "clip.mp4",
            "passed": True,
            "provider": "cloud_avatar",
            "consistency_score": 0.8,
            "diagnosis_category": None,
            "degraded": False,
            "retry_count": 0,
            "cost_usd": None,
        }
    ]
    assert set(result["gate_reports"]) == {
        "script",
        "voiceover",
        "shotlist",
        "avatar_manifest",
        "music_plan",
        "final",
    }


@pytest.mark.asyncio
async def test_render_episode_assigns_distinct_voices_per_present_character(tmp_path):
    """2026-07-13 治"导演台多身份锁脸"的音频版:多角色对话此前只有一个默认声音。
    render_episode 现在给 characters_present 里每个角色轮流分配一个 CURATED_VOICES
    音色,不是留空让下游全用同一个默认值。"""
    script = Script(
        lines=[ScriptLine(line_id="LN001", type="dialogue", speaker="C002", text="你被开除了。")]
    )
    timeline = Timeline(audio_segments=[AudioSegment(line_id="LN001", duration_ms=2000)])
    shotlist = ShotList(shots=[Shot(shot_id="1-1", line_ids=["LN001"], characters=["C002"])])
    frame_manifest = FrameManifest(frames=[ShotFrame(shot_id="1-1", scene_id="", degraded=False)])
    final_video = FinalVideo(video_path=str(tmp_path / "final.mp4"))

    build_voiceover_mock = AsyncMock(return_value=(timeline, _passing_gate()))

    with (
        patch(
            "hevi.tongjian.script.build_script", AsyncMock(return_value=(script, _passing_gate()))
        ),
        patch("hevi.tongjian.voiceover.build_voiceover", build_voiceover_mock),
        patch(
            "hevi.tongjian.shotlist.build_shotlist",
            AsyncMock(return_value=(shotlist, _passing_gate())),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar.build_frame_manifest_avatar",
            AsyncMock(return_value=frame_manifest),
        ),
        patch(
            "hevi.tongjian.music_plan.build_music_plan",
            AsyncMock(return_value=(MusicPlan(), _passing_gate())),
        ),
        patch(
            "hevi.tongjian.assemble.build_final_video",
            AsyncMock(return_value=(final_video, _passing_gate())),
        ),
    ):
        await bridge.render_episode(
            _episode(), _story(), run_dir=tmp_path, llm=AsyncMock(), tts_fn=AsyncMock()
        )

    _, kwargs = build_voiceover_mock.call_args
    voice_by_speaker = kwargs["voice_by_speaker"]
    # _episode() 的 characters_present = ["C001", "C002"]——两个角色必须拿到不同音色。
    assert voice_by_speaker["C001"] != voice_by_speaker["C002"]
    assert set(voice_by_speaker) == {"C001", "C002"}


@pytest.mark.asyncio
async def test_render_episode_passes_shortdrama_persona_and_event_locations(tmp_path):
    """2026-07-12 短剧真实反馈"大部分是旁白没对话"+"场景乱切"根因都在这两处没接:
    build_script 用的是通鉴默认人设(没参数化),build_shotlist 没拿到 event 的地点信息。
    这里只断言这两处真的把短剧专属的值传下去了,不重复测 script.py/shotlist.py 自己的逻辑。
    """
    story = _story()
    story.events[0].location = "写字楼工位"
    story.events[1].location = "写字楼工位"  # 两个事件同地点,应共用一个 scene_id

    script = Script(
        lines=[ScriptLine(line_id="LN001", type="dialogue", speaker="C002", text="你被开除了。")]
    )
    timeline = Timeline(audio_segments=[AudioSegment(line_id="LN001", duration_ms=2000)])
    shotlist = ShotList(shots=[Shot(shot_id="1-1", line_ids=["LN001"], characters=["C002"])])
    frame_manifest = FrameManifest(frames=[ShotFrame(shot_id="1-1", scene_id="", degraded=False)])
    final_video = FinalVideo(video_path=str(tmp_path / "final.mp4"))

    build_script_mock = AsyncMock(return_value=(script, _passing_gate()))
    build_shotlist_mock = AsyncMock(return_value=(shotlist, _passing_gate()))

    with (
        patch("hevi.tongjian.script.build_script", build_script_mock),
        patch(
            "hevi.tongjian.voiceover.build_voiceover",
            AsyncMock(return_value=(timeline, _passing_gate())),
        ),
        patch("hevi.tongjian.shotlist.build_shotlist", build_shotlist_mock),
        patch(
            "hevi.tongjian.scene_render_avatar.build_frame_manifest_avatar",
            AsyncMock(return_value=frame_manifest),
        ),
        patch(
            "hevi.tongjian.music_plan.build_music_plan",
            AsyncMock(return_value=(MusicPlan(), _passing_gate())),
        ),
        patch(
            "hevi.tongjian.assemble.build_final_video",
            AsyncMock(return_value=(final_video, _passing_gate())),
        ),
    ):
        await bridge.render_episode(
            _episode(), story, run_dir=tmp_path, llm=AsyncMock(), tts_fn=AsyncMock()
        )

    _, script_kwargs = build_script_mock.call_args
    assert script_kwargs["screenwriter_persona"] == bridge.DEFAULT_SHORTDRAMA_SCREENWRITER_PERSONA
    assert script_kwargs["include_commentary"] is False

    _, shotlist_kwargs = build_shotlist_mock.call_args
    assert shotlist_kwargs["event_locations"] == {"E001": "写字楼工位", "E002": "写字楼工位"}


@pytest.mark.asyncio
async def test_render_episode_raises_when_script_is_empty_shell(tmp_path):
    """L2 剧本生成 LLM 失败会返回空壳(script.py 既有降级行为)——不该假装成功继续跑
    后面几层空耗真钱,直接抛出去让调用方标 failed。"""
    empty_script = Script(lines=[])
    failing_gate = GateResult(passed=False, coverage=0.0, errors=["LLM 调用失败"])

    with patch(
        "hevi.tongjian.script.build_script",
        AsyncMock(return_value=(empty_script, failing_gate)),
    ):
        with pytest.raises(RuntimeError, match="剧本生成为空壳"):
            await bridge.render_episode(
                _episode(), _story(), run_dir=tmp_path, llm=AsyncMock(), tts_fn=AsyncMock()
            )


@pytest.mark.asyncio
async def test_render_episode_degrades_gracefully_when_music_plan_fails(tmp_path):
    """L7 音乐规划非致命——按通鉴 router 既有惯例降级为无音乐,不拖垮整集。"""
    script = Script(lines=[ScriptLine(line_id="LN001", type="narration", text="旁白")])
    timeline = Timeline(audio_segments=[AudioSegment(line_id="LN001", duration_ms=2000)])
    shotlist = ShotList(shots=[Shot(shot_id="1-1", line_ids=["LN001"])])
    frame_manifest = FrameManifest(
        frames=[ShotFrame(shot_id="1-1", scene_id="", clip_path="clip.mp4", degraded=False)]
    )
    final_video = FinalVideo(video_path=str(tmp_path / "final.mp4"))

    with (
        patch(
            "hevi.tongjian.script.build_script", AsyncMock(return_value=(script, _passing_gate()))
        ),
        patch(
            "hevi.tongjian.voiceover.build_voiceover",
            AsyncMock(return_value=(timeline, _passing_gate())),
        ),
        patch(
            "hevi.tongjian.shotlist.build_shotlist",
            AsyncMock(return_value=(shotlist, _passing_gate())),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar.build_frame_manifest_avatar",
            AsyncMock(return_value=frame_manifest),
        ),
        patch(
            "hevi.tongjian.music_plan.build_music_plan",
            AsyncMock(side_effect=RuntimeError("boom")),
        ),
        patch(
            "hevi.tongjian.assemble.build_final_video",
            AsyncMock(return_value=(final_video, _passing_gate())),
        ) as mock_final,
    ):
        result = await bridge.render_episode(
            _episode(), _story(), run_dir=tmp_path, llm=AsyncMock(), tts_fn=AsyncMock()
        )

    assert result["final_video"] is final_video
    # 降级成空 MusicPlan 传给 build_final_video,而不是让异常往上冒
    assert mock_final.call_args.kwargs["music_plan"] == MusicPlan()
