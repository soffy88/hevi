"""hevi.director.cut_style 测试 — 纯函数,无 ffmpeg/网络依赖。"""

from __future__ import annotations

from hevi.director.cut_style import classify_seam_cut_style
from hevi.director.pipeline_schemas import SceneScriptDialogueLine, SceneScriptSegment


def _seg(
    *, camera_movement: str = "", dialogue_speaker: str = "", dialogue_text: str = "台词"
) -> SceneScriptSegment:
    dialogue = (
        [SceneScriptDialogueLine(character_name=dialogue_speaker, text=dialogue_text)]
        if dialogue_speaker
        else []
    )
    return SceneScriptSegment(camera_movement=camera_movement, dialogue=dialogue)


def test_same_speaker_continues_across_seam_is_j_cut() -> None:
    seg_a = _seg(camera_movement="静态对话", dialogue_speaker="王生")
    seg_b = _seg(camera_movement="峰值轻推", dialogue_speaker="王生")
    decision = classify_seam_cut_style(seg_a, seg_b)
    assert decision.style == "J"
    assert decision.offset_s == 0.4


def test_reaction_shot_with_prior_dialogue_is_l_cut() -> None:
    seg_a = _seg(camera_movement="静态对话", dialogue_speaker="王生")
    seg_b = _seg(camera_movement="反应插入", dialogue_speaker="")
    decision = classify_seam_cut_style(seg_a, seg_b)
    assert decision.style == "L"
    assert decision.offset_s == 0.4


def test_neither_condition_returns_none() -> None:
    seg_a = _seg(camera_movement="静态对话", dialogue_speaker="王生")
    seg_b = _seg(camera_movement="横移", dialogue_speaker="老道士")
    decision = classify_seam_cut_style(seg_a, seg_b)
    assert decision.style is None
    assert decision.offset_s == 0.0


def test_reaction_marker_without_prior_dialogue_is_not_l_cut() -> None:
    seg_a = _seg(camera_movement="静态对话", dialogue_speaker="")
    seg_b = _seg(camera_movement="反应插入", dialogue_speaker="")
    decision = classify_seam_cut_style(seg_a, seg_b)
    assert decision.style is None


def test_l_cut_takes_priority_when_both_conditions_could_apply() -> None:
    # seg_b 既是反应镜头,又碰巧说话人跟 seg_a 一样(边界情况)——L 优先。
    seg_a = _seg(camera_movement="静态对话", dialogue_speaker="王生")
    seg_b = _seg(camera_movement="反应插入", dialogue_speaker="王生")
    decision = classify_seam_cut_style(seg_a, seg_b)
    assert decision.style == "L"


def test_custom_offset_is_respected() -> None:
    seg_a = _seg(camera_movement="静态对话", dialogue_speaker="王生")
    seg_b = _seg(camera_movement="峰值轻推", dialogue_speaker="王生")
    decision = classify_seam_cut_style(seg_a, seg_b, offset_s=0.3)
    assert decision.offset_s == 0.3
