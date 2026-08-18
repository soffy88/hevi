"""h3_compiler 单测 —— 镜头契约 → H3 三段式 render(纯逻辑,无网络)。"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from hevi.prompt.h3_compiler import (
    H3Render,
    action_block,
    alignment_instruction,
    character_block,
    compile_h3_prompt,
    compile_h3_segment,
    cut_starts,
    dialogue_block,
    pack_h3_segments,
    scene_block,
    validate_h3_alignment,
)


@dataclass
class FakeLine:
    character_name: str
    text: str
    target_name: str = ""


@dataclass
class FakeShot:
    scene_name: str = "雨夜街口"
    scene_description: str = "霓虹灯下的积水路面"
    shot_size: str = "中景"
    camera: str = "跟拍"
    character_names: list[str] = field(default_factory=lambda: ["林晚"])
    visual_prompt: str = "林晚撑伞快步走过街口"
    action_beats: list[str] = field(default_factory=list)
    dialogue_lines: list[FakeLine] = field(default_factory=list)
    shot_id: str = "S01"
    scene_no: int = 1
    duration_s: float = 3.0
    character_anchor: str = "黑长直,红围巾"


def test_scene_block() -> None:
    assert scene_block(scene_name="雨夜街口", scene_description="霓虹灯") == (
        "【场景】雨夜街口: 霓虹灯。"
    )


def test_character_block_s_number_and_anchor() -> None:
    assert character_block(name="林晚", s_no=1, anchor="黑长直", shot_size="中景") == (
        "【人物】林晚（S1，黑长直），中景"
    )


def test_dialogue_block_zh_no_translation_funnel() -> None:
    # zh 直出:对白原文进 <d>[Chinese] …</d>,不做任何英文转换
    block = dialogue_block(name="林晚", s_no=1, text="看什么看？跟我走吧。")
    assert "（S1）林晚说道：" in block
    assert "<d>[Chinese] 看什么看？跟我走吧。</d>" in block


def test_dialogue_block_quote_id_traceability() -> None:
    block = dialogue_block(name="林晚", s_no=1, text="别回头。", quote_id="q-1024")
    assert block.endswith("[q:q-1024]")


def test_action_block_prefers_beats() -> None:
    beats = action_block(action_beats=["撑伞", "快步走"], visual_prompt="x")
    assert beats == "【动作】撑伞；快步走。"
    assert action_block(action_beats=[], visual_prompt="林晚站着") == "【动作】林晚站着。"


def test_compile_full_shot_render() -> None:
    shot = FakeShot(dialogue_lines=[FakeLine(character_name="林晚", text="别回头。")])
    render = compile_h3_prompt(shot=shot, cast={"林晚": 1})
    integrated = render.integrated_multimodal_description
    assert "【场景】雨夜街口" in integrated
    assert "机位:跟拍" in integrated
    assert "【人物】林晚（S1，黑长直,红围巾），中景" in integrated
    assert "【动作】林晚撑伞快步走过街口" in integrated
    assert "（S1）林晚说道：" in integrated
    assert "<d>[Chinese] 别回头。</d>" in integrated
    assert render.overall_soundscape
    assert render.non_diegetic_music


def test_compile_multi_line_warns_and_takes_first() -> None:
    shot = FakeShot(
        dialogue_lines=[
            FakeLine(character_name="林晚", text="第一句。"),
            FakeLine(character_name="林晚", text="第二句。"),
        ]
    )
    render = compile_h3_prompt(shot=shot, cast={"林晚": 1})
    assert "第一句。" in render.integrated_multimodal_description
    assert "第二句。" not in render.integrated_multimodal_description


def test_compile_unknown_character_gets_s0_warning() -> None:
    shot = FakeShot(character_names=["路人甲"], dialogue_lines=[])
    render = compile_h3_prompt(shot=shot, cast={"林晚": 1})
    text = render.integrated_multimodal_description
    assert "（S0）" in text or "路人甲" in text


def test_scene_block_override_wins() -> None:
    shot = FakeShot()
    render = compile_h3_prompt(
        shot=shot, cast={"林晚": 1}, scene_block_text="【场景】母卡锁定场景。"
    )
    assert "母卡锁定场景" in render.integrated_multimodal_description
    assert "雨夜街口" not in render.integrated_multimodal_description


def test_render_from_dict_and_str() -> None:
    d = H3Render.from_dict(
        {
            "integrated_multimodal_description": "a",
            "overall_soundscape": "b",
            "non_diegetic_music": "c",
        }
    )
    assert d.to_dict() == {
        "integrated_multimodal_description": "a",
        "overall_soundscape": "b",
        "non_diegetic_music": "c",
    }
    s = H3Render.from_dict("整段描述")
    assert s.integrated_multimodal_description == "整段描述"
    assert s.overall_soundscape  # 回落缺省


@pytest.mark.parametrize(
    "duration_s,expected",
    [
        (5.0, 124),  # 124 = 17×7+5(官方模板 ~5s)
        (8.0, 192),  # 192 = 17×11+5
        (6.0, 158),  # round(144) → 144%17=8 → +14 = 158
        (0.5, 22),  # 22 = 17×1+5;provider 层再夹到 _H3_MIN_LENGTH=124
        (100.0, 2402),  # 2400%17=3 → +2 = 2402(17×141+5)
    ],
)
def test_h3_length_grid(duration_s: float, expected: int) -> None:
    from hevi.providers.h3_local.comfy_client import h3_length_for_duration

    length = h3_length_for_duration(duration_s)
    assert length == expected, f"{duration_s}s → {length}, 期望 {expected}"
    # 网格纪律:任何合法输出必须 ≡ 5 (mod 17)
    assert length % 17 == 5


def test_cut_starts_and_alignment_are_derived() -> None:
    starts = cut_starts([3.0, 4.0, 2.5])
    assert starts == [0.0, 3.0, 7.0]
    line = alignment_instruction(starts)
    assert "Picture 1 aligns with the 0.00-second mark" in line
    assert "Picture 2 aligns with the 3.00-second mark" in line
    assert "Picture 3 aligns with the 7.00-second mark" in line


def test_compile_h3_segment_alignment_matches_durations() -> None:
    shots = [
        FakeShot(shot_id="A", duration_s=3.0),
        FakeShot(shot_id="B", duration_s=4.0, visual_prompt="林晚停步回头"),
    ]
    render = compile_h3_segment(shots, cast={"林晚": 1})
    text = render.integrated_multimodal_description
    assert validate_h3_alignment(text, [3.0, 4.0]) == []
    assert "[Shot 1] 0.00s" in text
    assert "[Shot 2] 3.00s" in text
    assert "林晚停步回头" in text


def test_validate_h3_alignment_catches_stale_times() -> None:
    render = compile_h3_segment(
        [FakeShot(duration_s=3.0), FakeShot(duration_s=3.0)],
        cast={"林晚": 1},
    )
    drifted = render.integrated_multimodal_description.replace("3.00", "4.00")
    errors = validate_h3_alignment(drifted, [3.0, 3.0])
    assert any("3.00" in e for e in errors)


def test_pack_h3_segments_same_scene_caps_at_15() -> None:
    shots = [FakeShot(shot_id=f"S{i}", scene_no=1, duration_s=4.0) for i in range(5)]
    groups = pack_h3_segments(shots)
    assert [sum(s.duration_s for s in g) for g in groups] == [12.0, 8.0]


def test_pack_h3_segments_breaks_on_scene_change() -> None:
    shots = [
        FakeShot(shot_id="A", scene_no=1, duration_s=3.0),
        FakeShot(shot_id="B", scene_no=2, duration_s=3.0),
    ]
    groups = pack_h3_segments(shots)
    assert len(groups) == 2
