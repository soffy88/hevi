"""hevi.director.scene_script 测试 — 这个模块此前零测试覆盖,补 SPEC-007 新增部分(§6 六条
schema/prompt 解析、beat_description、no_cut_to、双约束 lint)+ 这轮实质性重写的
`lint_camera_movement_variety`(重写了该补,不是回填旧测试债),不补
`generate_scene_script_draft`/`lint_dialogue_segment_alignment` 的测试债(未改动)。"""

from __future__ import annotations

import json

from hevi.director.pipeline_schemas import (
    DesignList,
    SceneScriptDialogueLine,
    SceneScriptSegment,
    ScreenplayScene,
    WorldBible,
)
from hevi.director.scene_script import (
    generate_scene_script_draft,
    lint_beat_and_dialogue_boundary,
    lint_camera_movement_variety,
)


def _fake_llm(payload: dict):
    def _llm(*, messages, max_tokens):
        return {"content": json.dumps(payload, ensure_ascii=False)}

    return _llm


def _scene(**overrides) -> ScreenplayScene:
    defaults = {"scene_no": 1, "time": "暮色", "location": "山门前", "characters_present": ["王生"]}
    defaults.update(overrides)
    return ScreenplayScene(**defaults)


async def test_generate_scene_script_draft_parses_spec007_fields() -> None:
    payload = {
        "no_cut_to": ["不切到门外街道"],
        "segments": [
            {
                "t_start_s": 0.0,
                "t_end_s": 4.0,
                "narrative_text": "王生跪地叩首",
                "camera_movement": "静态对话",
                "beat_description": "王生额头触地的一瞬",
                "handoff_out": "王生俯身静止",
                "offscreen_trigger": "画外传来钟声",
                "dialogue": [],
            }
        ],
    }
    script = await generate_scene_script_draft(
        scene=_scene(),
        design_list=DesignList(),
        world_bible=WorldBible(),
        llm=_fake_llm(payload),
    )
    assert script.no_cut_to == ["不切到门外街道"]
    assert len(script.segments) == 1
    seg = script.segments[0]
    assert seg.beat_description == "王生额头触地的一瞬"
    assert seg.offscreen_trigger == "画外传来钟声"


async def test_generate_scene_script_draft_no_cut_to_falls_back_to_prev_when_missing() -> None:
    payload = {
        "segments": [
            {
                "t_start_s": 0.0,
                "t_end_s": 3.0,
                "narrative_text": "王生起身",
                "beat_description": "起身",
            }
        ]
    }
    script = await generate_scene_script_draft(
        scene=_scene(),
        design_list=DesignList(),
        world_bible=WorldBible(),
        llm=_fake_llm(payload),
        prev_no_cut_to=["不切到石狮特写"],
    )
    assert script.no_cut_to == ["不切到石狮特写"]


async def test_generate_scene_script_draft_fallback_gives_beat_placeholder() -> None:
    def _broken_llm(*, messages, max_tokens):
        raise RuntimeError("boom")

    script = await generate_scene_script_draft(
        scene=_scene(narration="王生缓步走向山门"),
        design_list=DesignList(),
        world_bible=WorldBible(),
        llm=_broken_llm,
    )
    assert script.segments
    assert all(seg.beat_description for seg in script.segments)


def _seg(
    *, beat: str = "有节拍", start: float = 0.0, dur: float = 3.0, chars: int = 0
) -> SceneScriptSegment:
    dialogue = [SceneScriptDialogueLine(character_name="王生", text="x" * chars)] if chars else []
    return SceneScriptSegment(
        segment_id="sg001",
        t_start_s=start,
        t_end_s=start + dur,
        beat_description=beat,
        dialogue=dialogue,
    )


def test_lint_beat_and_dialogue_boundary_passes_when_both_conditions_met() -> None:
    seg = _seg(beat="王生跪地", dur=3.0, chars=2)  # 2字台词,3s 时长,估算需要远小于3s
    findings = lint_beat_and_dialogue_boundary([seg])
    assert findings == []


def test_lint_beat_and_dialogue_boundary_flags_missing_beat_only() -> None:
    seg = _seg(beat="", dur=3.0, chars=2)
    findings = lint_beat_and_dialogue_boundary([seg])
    assert len(findings) == 1
    assert "节拍边界条件不满足" in findings[0]


def test_lint_beat_and_dialogue_boundary_flags_missing_dialogue_fit_only() -> None:
    seg = _seg(beat="王生跪地", dur=1.0, chars=20)  # 20字台词,1s 时长装不下
    findings = lint_beat_and_dialogue_boundary([seg])
    assert len(findings) == 1
    assert "语句边界条件不满足" in findings[0]


def test_lint_beat_and_dialogue_boundary_flags_both_missing() -> None:
    seg = _seg(beat="", dur=1.0, chars=20)
    findings = lint_beat_and_dialogue_boundary([seg])
    assert len(findings) == 1
    assert "两个条件都不满足" in findings[0]


# ── lint_camera_movement_variety(2026-07-20 重新定义)────────────────────────


def _cam_seg(*, camera: str, speaker: str = "", offscreen: str = "") -> SceneScriptSegment:
    dialogue = [SceneScriptDialogueLine(character_name=speaker, text="x")] if speaker else []
    return SceneScriptSegment(
        segment_id="sg", camera_movement=camera, dialogue=dialogue, offscreen_trigger=offscreen
    )


def test_camera_lint_allows_repeated_static_with_no_shift_signal() -> None:
    segs = [
        _cam_seg(camera="静态对话", speaker="许渔夫"),
        _cam_seg(camera="静态对话", speaker="许渔夫"),
    ]
    assert lint_camera_movement_variety(segs) == []


def test_camera_lint_flags_repeated_push_in_as_warning() -> None:
    # 两段都是 push-in 类(标签不必完全相同),连续重复本身就该报——这个 2 段全 push-in 的
    # 极端例子同时也会撞上占比>1/4 那条既有检查,两条都是真实成立的问题,不是重复计数的 bug。
    segs = [_cam_seg(camera="定场推"), _cam_seg(camera="峰值轻推")]
    findings = lint_camera_movement_variety(segs)
    assert any(f.startswith("[警告]") and "重复推拉" in f for f in findings)


def test_camera_lint_soft_hint_on_speaker_change() -> None:
    segs = [
        _cam_seg(camera="静态对话", speaker="许渔夫"),
        _cam_seg(camera="静态对话", speaker="王六郎"),
    ]
    findings = lint_camera_movement_variety(segs)
    assert len(findings) == 1
    assert findings[0].startswith("[提示]")


def test_camera_lint_soft_hint_on_offscreen_trigger() -> None:
    segs = [
        _cam_seg(camera="静态对话", speaker="许渔夫"),
        _cam_seg(camera="静态对话", speaker="许渔夫", offscreen="画外传来钟声"),
    ]
    findings = lint_camera_movement_variety(segs)
    assert len(findings) == 1
    assert findings[0].startswith("[提示]")


def test_camera_lint_push_in_ratio_still_flagged_even_when_not_consecutive() -> None:
    segs = [
        _cam_seg(camera="定场推"),
        _cam_seg(camera="静态对话"),
        _cam_seg(camera="反应插入"),
        _cam_seg(camera="峰值轻推"),
    ]
    findings = lint_camera_movement_variety(segs)
    assert any("占比" in f and f.startswith("[警告]") for f in findings)


def test_camera_lint_different_adjacent_labels_no_finding() -> None:
    segs = [_cam_seg(camera="静态对话"), _cam_seg(camera="横移")]
    assert lint_camera_movement_variety(segs) == []
