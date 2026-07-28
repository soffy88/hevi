"""正反打渲染消费测试(③④b,2026-07-25):produce_v2/multirole 读 shot_type/side/fg 生成
构图指令 + 侧位锁定 + 只动说话人脸 + 背景不渲台词。"""

from __future__ import annotations

from hevi.director.multirole_reference import _reverse_shot_directive, compile_multirole_prompt
from hevi.director.pipeline_schemas import (
    SceneAxis,
    SceneScript,
    SceneScriptDialogueLine,
    SceneScriptSegment,
    SceneStage,
)
from hevi.director.produce_v2 import _segment_character_names


def _ots_seg() -> SceneScriptSegment:
    return SceneScriptSegment(
        segment_id="sg002",
        shot_type="ots",
        speaker_side="画左",
        foreground_character="李斯",
        dialogue=[SceneScriptDialogueLine(character_name="王绾", text="请立诸子。")],
    )


# ── ③ 构图指令 ────────────────────────────────────────────────────────────
def test_ots_directive_locks_side_and_speaker() -> None:
    d = _reverse_shot_directive(_ots_seg())
    assert "过肩反打" in d
    assert "王绾" in d and "画左" in d  # 说话人 + 己侧
    assert "李斯" in d and "画右" in d  # 前景对手在对侧
    assert "不许翻" in d  # 防跳轴
    assert "只有王绾在开口说话" in d  # 只动说话人


def test_frontal_directive_is_throne_solo() -> None:
    seg = SceneScriptSegment(
        shot_type="frontal",
        dialogue=[SceneScriptDialogueLine(character_name="秦始皇", text="廷尉议是。")],
    )
    d = _reverse_shot_directive(seg)
    assert "君主" in d and "略仰" in d and "不切入反打轴线" in d


def test_master_directive_builds_axis() -> None:
    d = _reverse_shot_directive(SceneScriptSegment(shot_type="master"))
    assert "建立镜" in d and "左右轴线" in d


def test_single_shot_has_no_reverse_directive() -> None:
    assert _reverse_shot_directive(SceneScriptSegment(shot_type="single")) == ""


# ── ③ 每段实际入镜角色 ─────────────────────────────────────────────────────
def _script() -> SceneScript:
    return SceneScript(scene_ref=1, characters_present=["王绾", "李斯", "秦始皇"])


def test_ots_renders_speaker_plus_foreground() -> None:
    refs = {"王绾": "a.png", "李斯": "b.png", "秦始皇": "c.png"}
    assert _segment_character_names(_ots_seg(), _script(), refs) == ["王绾", "李斯"]


def test_frontal_renders_speaker_only() -> None:
    seg = SceneScriptSegment(
        shot_type="frontal",
        dialogue=[SceneScriptDialogueLine(character_name="秦始皇", text="议是。")],
    )
    refs = {"王绾": "a.png", "李斯": "b.png", "秦始皇": "c.png"}
    assert _segment_character_names(seg, _script(), refs) == ["秦始皇"]


def test_master_renders_all_present() -> None:
    refs = {"王绾": "a.png", "李斯": "b.png", "秦始皇": "c.png"}
    seg = SceneScriptSegment(shot_type="master")
    assert _segment_character_names(seg, _script(), refs) == ["王绾", "李斯", "秦始皇"]


# ── ④b 背景不渲台词 ───────────────────────────────────────────────────────
def test_prompt_forbids_dialogue_as_background_text() -> None:
    prompt = compile_multirole_prompt(
        action_text="王绾进言。",
        scene_stage=SceneStage(scene_ref=1, axis=SceneAxis()),
        character_names=["王绾"],
        scene_plate_path=None,
    )
    assert "不要把任何台词" in prompt and "牌匾" in prompt


def test_ots_prompt_carries_reverse_directive() -> None:
    prompt = compile_multirole_prompt(
        action_text="王绾进言。",
        scene_stage=SceneStage(scene_ref=1, axis=SceneAxis()),
        character_names=["王绾", "李斯"],
        scene_plate_path=None,
        reverse_shot_directive_text=_reverse_shot_directive(_ots_seg()),
    )
    assert "过肩反打" in prompt and "不许翻" in prompt
