"""DRAMAPLAN 第四轮返工（F1–F5）回归测试：分镜不丢台词/旁白、tts 质量、改稿守卫、拆分均衡、画风参数。"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from hevi.layer4_legacy.script2video.oskill_impl.shot_budget import split_single_shot_plan
from hevi.storygraph.review import (
    DEFAULT_STORYBOARD_STYLE,
    MIN_SHOT_DURATION_S,
    AdaptationDecision,
    EpisodeScript,
    ReviewIssue,
    ScriptLine,
    ScriptScene,
    deterministic_checks,
    revise_episode_script_async,
    script_to_storyboard,
    storyboard_coverage,
)
from hevi.storygraph.schemas import StoryCharacter as Character
from hevi.storygraph.schemas import StoryEvent as Event
from hevi.storygraph.schemas import StoryGraph, StoryMeta


def _book() -> StoryGraph:
    return StoryGraph(
        meta=StoryMeta(source="test"),
        characters=[
            Character(char_id="C001", name="少爷"),
            Character(char_id="C002", name="福伯"),
        ],
        events=[
            Event(event_id="E1", summary="少爷离家", actors=["C001", "C002"], location="老宅"),
            Event(event_id="E2", summary="福伯送别", actors=["C002"], location="门口"),
        ],
    )


def _scene_9_lines(shot_count: int = 6) -> ScriptScene:
    lines = [
        ("少爷", "福伯，我要走了。"),
        ("福伯", "少爷，盘缠我备好了。"),
        ("少爷", "母亲临走前说过什么？"),
        ("福伯", "她说……你不是在逃，是去寻找属于你的光。"),
        ("少爷", "真的有血缘？"),
        ("福伯", "我信她的话……也信你。"),
        ("少爷", "……谢谢您。我不会让她失望的。"),
        ("福伯", "路上小心！"),
        ("少爷", "等我回来"),
    ]
    return ScriptScene(
        scene_no=2,
        location="老宅门口",
        event_ids=["E1", "E2"],
        summary="少爷与福伯告别",
        narration="天色微明。老宅门前的灯笼还亮着。",
        dialogue=[ScriptLine(speaker=s, text=t) for s, t in lines],
        shot_count=shot_count,
        duration_s=30.0,
    )


def test_f1_all_dialogue_and_narration_reach_storyboard():
    script = EpisodeScript(ep_number=1, scenes=[_scene_9_lines(6)])
    sb = script_to_storyboard(script, _book())
    assert len(sb.shots) == 6
    cov = storyboard_coverage(script, sb)
    assert cov["coverage"] == 1.0, cov["missing"]
    joined = "".join(s.tts_text for s in sb.shots)
    for key in ("你不是在逃，是去寻找属于你的光", "我信她的话……也信你", "我不会让她失望的", "天色微明"):
        assert key in joined
    # 顺序保留：旁白在前，对白按剧本顺序
    assert joined.index("天色微明") < joined.index("福伯，我要走了") < joined.index("等我回来")


def test_f1_no_truncation_when_over_budget_merges_instead():
    from hevi.storygraph.schemas import OutlineEpisode

    scenes = [_scene_9_lines(6), _scene_9_lines(6).model_copy(update={"scene_no": 3})]
    script = EpisodeScript(ep_number=1, scenes=scenes)
    ep = OutlineEpisode(ep_number=1, title="t", target_duration_s=60, shot_budget=8)
    sb = script_to_storyboard(script, _book(), ep)
    assert len(sb.shots) <= 8
    assert storyboard_coverage(script, sb)["coverage"] == 1.0


def test_f2_tts_has_no_camera_prefix_or_speaker_prefix_and_keeps_question_marks():
    script = EpisodeScript(ep_number=1, scenes=[_scene_9_lines(12)])
    sb = script_to_storyboard(script, _book())
    for shot in sb.shots:
        for bad in ("动作特写：", "环境细节：", "人物近景：", "镜头拉开：", "少爷：", "福伯："):
            assert bad not in shot.tts_text
        assert "……。" not in shot.tts_text
        assert "？。" not in shot.tts_text
    joined = "".join(s.tts_text for s in sb.shots)
    assert "真的有血缘？" in joined
    assert "母亲临走前说过什么？" in joined
    assert "路上小心！" in joined
    assert "等我回来。" in joined  # 无句末标点时才补"。"


def test_f2_shot_duration_floor_and_reading_time():
    scene = _scene_9_lines(4).model_copy(update={"duration_s": 2.0})
    script = EpisodeScript(ep_number=1, scenes=[scene])
    sb = script_to_storyboard(script, _book())
    for shot in sb.shots:
        assert shot.duration_s >= MIN_SHOT_DURATION_S
        chars = sum(1 for ch in shot.tts_text if ch.isalnum())
        assert shot.duration_s >= chars / 5.0  # ≥ 朗读时长


def test_f2_rule_layer_flags_scene_too_short():
    book = _book()
    decision = AdaptationDecision(ep_number=1, event_ids=["E1", "E2"])
    scene = _scene_9_lines(2).model_copy(update={"duration_s": 1.0})
    issues = deterministic_checks(EpisodeScript(ep_number=1, scenes=[scene]), book, decision)
    too_short = [i for i in issues if i.code == "scene_too_short"]
    assert too_short and too_short[0].severity == "error"


def test_f3_rule_layer_flags_scene_with_only_summary_as_empty():
    book = _book()
    decision = AdaptationDecision(ep_number=1, event_ids=["E1"])
    scene = ScriptScene(scene_no=1, event_ids=["E1"], summary="只有摘要", shot_count=1, duration_s=5)
    issues = deterministic_checks(EpisodeScript(ep_number=1, scenes=[scene]), book, decision)
    assert any(i.code == "empty_scene" and i.severity == "error" for i in issues)


async def test_f3_execution_layer_rejects_emptied_scene_rewrite():
    book = _book()
    scene = _scene_9_lines(4)
    script = EpisodeScript(ep_number=1, scenes=[scene])
    decision = AdaptationDecision(ep_number=1, event_ids=["E1", "E2"], target_shots=6, target_duration_s=40)

    async def emptying_llm(*, messages, max_tokens=1024, **kw):
        return {"content": json.dumps({"scene_no": 2, "summary": "改", "narration": "", "dialogue": []})}

    out = await revise_episode_script_async(
        script,
        [ReviewIssue(code="llm:pacing", message="节奏", scope="scene:2", scene_no=2)],
        book,
        decision,
        llm=emptying_llm,
    )
    new = out.scenes[0]
    assert new.dialogue, "空改写必须被拒收，保留原对白"
    assert len(new.dialogue) == len(scene.dialogue)


@dataclass
class _Plan:
    shot_id: str
    duration_s: float
    image_prompt: str
    tts_text: str


@pytest.mark.parametrize("count", [2, 3, 5, 7])
def test_f4_split_never_single_char_when_chars_allow(count):
    text = "甲乙丙丁戊己庚辛，壬癸。"
    parts = split_single_shot_plan(_Plan("s", 6.0, "p", text), count)
    assert "".join(p.tts_text for p in parts) == text
    lens = [len(p.tts_text) for p in parts]
    assert min(lens) >= 1
    if len(text) >= 2 * count:
        assert min(lens) >= 2
        assert max(lens) / min(lens) <= 2.5


def test_f4_split_without_punctuation_is_even():
    text = "没有标点的一长句话就这样一直说下去吧"
    parts = split_single_shot_plan(_Plan("s", 6.0, "p", text), 3)
    assert [len(p.tts_text) for p in parts] == [6, 6, 6]
    assert len({p.image_prompt for p in parts}) == 3


def test_f5_image_prompts_differ_per_shot_and_style_is_parameterised():
    script = EpisodeScript(ep_number=1, scenes=[_scene_9_lines(6)])
    sb = script_to_storyboard(script, _book())
    prompts = [s.image_prompt for s in sb.shots]
    assert len(set(prompts)) == len(prompts)
    assert all("写实短剧风格" not in p for p in prompts)
    assert all(DEFAULT_STORYBOARD_STYLE in p for p in prompts)
    sb2 = script_to_storyboard(script, _book(), style="水墨写意风格")
    assert all("水墨写意风格" in s.image_prompt for s in sb2.shots)


def test_f2_split_fragment_keeps_comma_not_forced_period():
    scene = ScriptScene(
        scene_no=1,
        event_ids=["E1"],
        narration="",
        dialogue=[ScriptLine(speaker="福伯", text="你走，便是放弃沈家半条命……但我拦不住你的脚。")],
        shot_count=2,
        duration_s=10,
    )
    sb = script_to_storyboard(EpisodeScript(ep_number=1, scenes=[scene]), _book())
    assert len(sb.shots) == 2
    assert "".join(s.tts_text for s in sb.shots) == "你走，便是放弃沈家半条命……但我拦不住你的脚。"
    assert all("。，" not in s.image_prompt for s in sb.shots)


def test_rule_layer_flags_foreign_token_in_dialogue():
    book = _book()
    decision = AdaptationDecision(ep_number=1, event_ids=["E1"])
    scene = ScriptScene(
        scene_no=1,
        event_ids=["E1"],
        dialogue=[ScriptLine(speaker="少爷", text="anfangs我不敢相信。")],
        shot_count=1,
        duration_s=5,
    )
    issues = deterministic_checks(EpisodeScript(ep_number=1, scenes=[scene]), book, decision)
    assert any(i.code == "foreign_token" for i in issues)


def test_r5_stage_directions_leave_tts_and_go_to_image_prompt():
    scene = ScriptScene(
        scene_no=1,
        event_ids=["E1"],
        dialogue=[
            ScriptLine(speaker="福伯", text="...（颤手接过玉玦，久久不语）"),
            ScriptLine(speaker="少爷", text="（缓缓将玉玦放入福伯掌心）它该归你了。"),
        ],
        shot_count=2,
        duration_s=8,
    )
    script = EpisodeScript(ep_number=1, scenes=[scene])
    sb = script_to_storyboard(script, _book())
    joined = "".join(s.tts_text for s in sb.shots)
    assert "（" not in joined and "(" not in joined and not joined.startswith(".")
    assert "它该归你了。" in joined
    prompts = " ".join(s.image_prompt for s in sb.shots)
    assert "颤手接过玉玦" in prompts and "缓缓将玉玦放入福伯掌心" in prompts
    assert storyboard_coverage(script, sb)["coverage"] == 1.0


def test_r5_rule_layer_flags_stage_direction_in_dialogue():
    decision = AdaptationDecision(ep_number=1, event_ids=["E1"])
    scene = ScriptScene(
        scene_no=1,
        event_ids=["E1"],
        dialogue=[ScriptLine(speaker="少爷", text="（叹气）走吧。")],
        shot_count=1,
        duration_s=5,
    )
    issues = deterministic_checks(EpisodeScript(ep_number=1, scenes=[scene]), _book(), decision)
    assert any(i.code == "stage_direction_in_dialogue" for i in issues)


def test_r5_spare_budget_avoids_mixing_two_speakers_in_one_shot():
    from hevi.storygraph.schemas import OutlineEpisode

    scene = ScriptScene(
        scene_no=1,
        event_ids=["E1"],
        dialogue=[
            ScriptLine(speaker="福伯", text="少爷，盘缠备好了。"),
            ScriptLine(speaker="少爷", text="多谢福伯。"),
            ScriptLine(speaker="福伯", text="路上小心。"),
        ],
        shot_count=2,
        duration_s=9,
    )
    ep = OutlineEpisode(ep_number=1, target_duration_s=30, shot_budget=6)
    sb = script_to_storyboard(EpisodeScript(ep_number=1, scenes=[scene]), _book(), ep)
    assert len(sb.shots) == 3
    assert all("、" not in s.speaker for s in sb.shots)


def test_r5_merge_prefers_same_speaker_when_no_spare_budget():
    scene = ScriptScene(
        scene_no=1,
        event_ids=["E1"],
        dialogue=[
            ScriptLine(speaker="福伯", text="少爷，盘缠备好了。"),
            ScriptLine(speaker="福伯", text="信也在里面。"),
            ScriptLine(speaker="少爷", text="多谢福伯。"),
        ],
        shot_count=2,
        duration_s=9,
    )
    sb = script_to_storyboard(EpisodeScript(ep_number=1, scenes=[scene]), _book())
    assert [s.speaker for s in sb.shots] == ["福伯", "少爷"]


def test_r5_split_short_text_has_no_punctuation_only_shot():
    parts = split_single_shot_plan(_Plan("s", 6.0, "p", "短。"), 3)
    assert [p.tts_text for p in parts] == ["短。", "", ""]
    parts = split_single_shot_plan(_Plan("s", 6.0, "p", "他说……我不知道……也许吧，明天再说。"), 2)
    assert not parts[1].tts_text.startswith("…")
