"""Strict prompt-readiness gates (2026-10-31 prompt audit, items 1-5).

Every rule has a positive and a negative case. Legacy (non-strict)
behaviour is asserted unchanged where it is deliberately kept:
an unknown tier is recorded, not blocking, on the legacy path.
"""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.prompt_compiler import (
    PromptCompilerError,
    check_beat_progression,
    check_rendered_shot_prompt,
    compile_episode,
    compile_generation_ready_episode,
    compile_shot_prompt,
    frames_for_provider,
)
from hevi.capabilities import scene_reference as sr


def _pic(tmp_path: Path, name: str) -> dict[str, str]:
    path = tmp_path / name
    data = f"readiness fixture {name}\n".encode("utf-8")
    path.write_bytes(data)
    return {"file": str(path), "sha256": hashlib.sha256(data).hexdigest()}


def _anchor(pic: dict[str, str], *, confirmed: bool = True) -> dict[str, object]:
    return {
        "character_id": "alan",
        "name": "阿兰",
        "anchor": {
            "file": pic["file"],
            "sha256": pic["sha256"],
            "look_snapshot": "二十多岁女子，象牙白缎面抹胸长裙，金色花朵发簪",
            "description_fingerprint": hashlib.sha256(b"alan look").hexdigest(),
            "confirmed": confirmed,
        },
        "views": [],
        "anchor_changes": 0,
    }


def _state() -> dict[str, object]:
    return {
        "人物": {"脸": "与参考图一致"},
        "服装": {"裙": "象牙白缎面抹胸长裙"},
        "道具": {"左手": "搭在月洞门石边沿"},
    }


def _episode() -> dict[str, object]:
    return {
        "episode_no": "READY",
        "title": "玉兰开了",
        "target_duration_s": 10.0,
        "aspect": "9:16",
        "style": "小红书新中式写真风格，奶白色调，低饱和，柔焦",
        "shots": [
            {
                "shot_no": "R01",
                "scene": "苏州园林风格中式古典园林，白墙圆形月洞门",
                "time_of_day": "春日午后",
                "duration_s": 10.0,
                "camera": {
                    "shot_size": "中景",
                    "shot_size_end": "中近景",
                    "angle": "平视",
                    "movement": "dolly_in",
                    "easing": "ease_in_out",
                    "start_frame": {
                        "state_kind": "trigger_in_progress",
                        "description": "人物站在月洞门边，微风未起",
                    },
                    "end_frame": {"description": "人物微笑看着镜头，花瓣飘落"},
                },
                "characters": ["阿兰"],
                "props": ["金色花朵发簪"],
                "continuity": {"entry_state": _state(), "exit_state": _state()},
                "negative_prompts": ["换脸", "发簪消失"],
                "fallbacks": [
                    {"trigger": "接花瓣失败", "replacement": "删掉递花瓣动作"},
                ],
                "beats": [
                    {"beat_no": 1, "t_start_s": 0.0, "t_end_s": 2.5,
                     "action": "微风吹过，玉兰枝摇动，花瓣飘落，人物看着镜头",
                     "sound": "风声"},
                    {"beat_no": 2, "t_start_s": 2.5, "t_end_s": 4.5,
                     "action": "人物把头轻轻转向画面左侧看向池水，再慢慢转回来看向镜头",
                     "sound": "风声、鸟叫", "camera_move": "dolly_in"},
                    {"beat_no": 3, "t_start_s": 4.5, "t_end_s": 5.5,
                     "action": "一片玉兰花瓣飘到身前，抬起手掌心向上接住花瓣",
                     "sound": "风声"},
                    {"beat_no": 4, "t_start_s": 5.5, "t_end_s": 8.3,
                     "action": "看着镜头轻声说话",
                     "sound": "古筝", "line": "玉兰开了",
                     "speaker": "阿兰", "line_mode": "dialogue"},
                    {"beat_no": 5, "t_start_s": 8.3, "t_end_s": 10.0,
                     "action": "轻轻歪头温柔地笑，保持微笑定格",
                     "sound": "古筝、风声"},
                ],
                "clips": [{"clip_id": "R01c1", "beats": [1, 2, 3, 4, 5]}],
            }
        ],
    }


def _ready_inputs(tmp_path: Path):
    scene_pic = _pic(tmp_path, "scene.png")
    alan_pic = _pic(tmp_path, "alan.png")
    return (
        {"阿兰": _anchor(alan_pic)},
        {1: scene_pic, 2: alan_pic},
    )


# ------------------------------------------------------------------ strict happy path


def test_strict_episode_renders_anchor_binding_and_frames(tmp_path: Path) -> None:
    anchors, bindings = _ready_inputs(tmp_path)
    result = compile_generation_ready_episode(
        _episode(), provider="fasth3_local", anchors=anchors,
        reference_bindings=bindings)
    assert result["tier"]["status"] == "checked"
    prompt = result["prompts"][0]["prompt"]
    assert "锚点已确认：二十多岁女子" in prompt
    assert "参考 Picture 2" in prompt
    assert "Picture 1：" in prompt and "Picture 2：" in prompt
    assert "240帧（24fps，fasth3_local）" in prompt
    assert prompt.count("[首帧]人物站在月洞门边，微风未起") == 1
    assert "玉兰开了" in prompt
    clip = result["clip_prompts"]["R01c1"]
    assert "Camera:" in clip and "State:" in clip and "Constraints:" in clip
    assert "Anchors:" in clip and "二十多岁女子" in clip
    assert "Frames: 240 (24fps, fasth3_local)" in clip
    assert "Negative list: 换脸; 发簪消失" in clip
    assert "画面里不许出现任何文字" in clip


def test_strict_episode_via_compile_episode_strict_flag(tmp_path: Path) -> None:
    anchors, bindings = _ready_inputs(tmp_path)
    result = compile_episode(
        _episode(), provider="fasth3_local", anchors=anchors,
        reference_bindings=bindings, strict=True)
    assert result["strict"] is True
    assert result["prompts"][0]["prompt"].count("人物站在月洞门边，微风未起") <= 2


# ------------------------------------------------------------------ item 3: provider


def test_strict_without_provider_fails(tmp_path: Path) -> None:
    anchors, bindings = _ready_inputs(tmp_path)
    with pytest.raises(PromptCompilerError, match="provider"):
        compile_episode(
            _episode(), anchors=anchors, reference_bindings=bindings, strict=True)


def test_strict_over_provider_cap_fails(tmp_path: Path) -> None:
    anchors, bindings = _ready_inputs(tmp_path)
    episode = _episode()
    episode["target_duration_s"] = 35.0
    shot = episode["shots"][0]
    shot["duration_s"] = 35.0
    spans = [(0.0, 5.0), (5.0, 12.0), (12.0, 18.0), (18.0, 28.0), (28.0, 35.0)]
    for beat, (start, end) in zip(shot["beats"], spans):
        beat["t_start_s"], beat["t_end_s"] = start, end
    with pytest.raises(PromptCompilerError, match="exceeds"):
        compile_generation_ready_episode(
            episode, provider="fasth3_local", anchors=anchors,
            reference_bindings=bindings)


def test_legacy_unknown_tier_still_recorded_not_blocking() -> None:
    result = compile_episode(_episode())
    assert result["tier"]["status"] == "unknown"
    assert "no provider selected" in result["tier"]["reason"]


# ------------------------------------------------------------------ items 1-2: anchors/bindings


def test_strict_missing_anchor_fails(tmp_path: Path) -> None:
    _, bindings = _ready_inputs(tmp_path)
    with pytest.raises(CapabilityError, match="no confirmed anchor"):
        compile_generation_ready_episode(
            _episode(), provider="fasth3_local", anchors={},
            reference_bindings=bindings)


def test_strict_unconfirmed_anchor_fails(tmp_path: Path) -> None:
    scene_pic = _pic(tmp_path, "scene.png")
    alan_pic = _pic(tmp_path, "alan.png")
    anchors = {"阿兰": _anchor(alan_pic, confirmed=False)}
    with pytest.raises(CapabilityError, match="not confirmed"):
        compile_generation_ready_episode(
            _episode(), provider="fasth3_local", anchors=anchors,
            reference_bindings={1: scene_pic, 2: alan_pic})


def test_strict_missing_picture_1_binding_fails(tmp_path: Path) -> None:
    anchors, bindings = _ready_inputs(tmp_path)
    bindings = {2: bindings[2]}
    with pytest.raises(PromptCompilerError, match="Picture 1"):
        compile_generation_ready_episode(
            _episode(), provider="fasth3_local", anchors=anchors,
            reference_bindings=bindings)


def test_strict_anchor_file_not_in_bindings_fails(tmp_path: Path) -> None:
    scene_pic = _pic(tmp_path, "scene.png")
    other_pic = _pic(tmp_path, "other.png")
    anchors = {"阿兰": _anchor(other_pic)}
    with pytest.raises(PromptCompilerError, match="not in reference_bindings"):
        compile_generation_ready_episode(
            _episode(), provider="fasth3_local", anchors=anchors,
            reference_bindings={1: scene_pic, 2: _pic(tmp_path, "alan.png")})


def test_strict_nonexistent_binding_file_fails(tmp_path: Path) -> None:
    anchors, bindings = _ready_inputs(tmp_path)
    bindings[1] = {"file": str(tmp_path / "does-not-exist.png"),
                   "sha256": "0" * 64}
    with pytest.raises(CapabilityError, match="does not exist"):
        compile_generation_ready_episode(
            _episode(), provider="fasth3_local", anchors=anchors,
            reference_bindings=bindings)


def test_shot_prompt_anchors_without_bindings_fails(tmp_path: Path) -> None:
    anchors, _ = _ready_inputs(tmp_path)
    with pytest.raises(PromptCompilerError, match="together"):
        compile_shot_prompt(_episode(), _episode()["shots"][0], anchors=anchors)


# ------------------------------------------------------------------ item 5: progression


def test_repeated_beats_fail_in_generation_shot() -> None:
    shot = copy.deepcopy(_episode()["shots"][0])
    shot["beats"] = [
        {"beat_no": i + 1, "t_start_s": i * 2.5, "t_end_s": (i + 1) * 2.5,
         "action": "人物站在月洞门边一动不动", "sound": "风声"}
        for i in range(4)
    ]
    with pytest.raises(PromptCompilerError, match="do not progress"):
        check_beat_progression(shot)


def test_repeated_beats_in_pure_still_shot_pass_progression() -> None:
    shot = copy.deepcopy(_episode()["shots"][0])
    shot["clips"] = []
    shot["beats"] = [
        {"beat_no": i + 1, "t_start_s": i * 2.5, "t_end_s": (i + 1) * 2.5,
         "action": "人物站在月洞门边一动不动", "sound": "风声"}
        for i in range(4)
    ]
    check_beat_progression(shot)  # no raise: pure still makes no generation call


def test_rendered_prompt_with_entry_text_in_segments_fails() -> None:
    shot = _episode()["shots"][0]
    stale = (
        "[风格]x\n[镜头段]\n"
        "[0–2秒]镜头（人物站在月洞门边，微风未起→走→保持本镜构图／静默）\n"
        "[出口状态]\n"
    )
    with pytest.raises(PromptCompilerError, match="首帧"):
        check_rendered_shot_prompt(stale, shot)


def test_strict_repeated_beats_fail_end_to_end(tmp_path: Path) -> None:
    anchors, bindings = _ready_inputs(tmp_path)
    episode = _episode()
    shot = episode["shots"][0]
    shot["beats"] = [
        {"beat_no": i + 1, "t_start_s": i * 2.5, "t_end_s": (i + 1) * 2.5,
         "action": "人物站在月洞门边一动不动", "sound": "风声"}
        for i in range(4)
    ]
    shot["clips"] = [{"clip_id": "R01c1", "beats": [1, 2, 3, 4]}]
    with pytest.raises(PromptCompilerError, match="do not progress"):
        compile_generation_ready_episode(
            episode, provider="fasth3_local", anchors=anchors,
            reference_bindings=bindings)


# ------------------------------------------------------------------ frame truth


def test_frame_truth_10s_is_240_fasth3_and_243_h3() -> None:
    assert frames_for_provider(10.0, "fasth3_local") == 240
    assert sr.h3_frame_count(10.0) == 243
    assert sr.canonical_frame_count(10.0, route="h3") == 243
    assert sr.canonical_frame_count(10.0, route="fasth3_local") == 240
    assert sr.fasth3_frame_count(10.0) == 240
    assert sr.canonical_frame_count(5.0, route="h3") == 124


# ------------------------------------------------------------------ item 4: scene_reference Chinese dialogue


def test_chinese_dialogue_rewrite_numbers_and_tags() -> None:
    rewritten, speakers = sr.rewrite_dialogue("守仁说：\"我想做圣贤。\"")
    assert speakers == ["守仁"]
    assert rewritten == "守仁 (S1) 说，<d>我想做圣贤。</d>"
    rewritten2, speakers2 = sr.rewrite_dialogue(
        "守仁说：\"我想做圣贤。\"先生问：\"为什么读书？\"")
    assert speakers2 == ["守仁", "先生"]
    assert "(S2)" in rewritten2


def test_scene_strict_chinese_plan_passes(tmp_path: Path) -> None:
    scene_pic = _pic(tmp_path, "scene.png")
    angle_pic = _pic(tmp_path, "angle.png")
    shouren_pic = _pic(tmp_path, "shouren.png")
    plan = {
        "scene": {"description": "A quiet schoolroom.", "framing": "Fixed camera, wide shot."},
        "characters": [
            {"name": "守仁", "description": "A twelve-year-old student in a grey-green robe.",
             "anchor": {
                 "file": shouren_pic["file"], "sha256": shouren_pic["sha256"],
                 "look_snapshot": "十二岁少年，灰绿长袍，蓝色头巾", "confirmed": True}},
        ],
        "angles": [{"description": "The same room from the doorway.",
                    "file": angle_pic["file"], "sha256": angle_pic["sha256"]}],
        "shots": [{"description": "守仁走进私塾。",
                   "dialogue": "守仁说：\"我想做圣贤。\""}],
        "soundscape": "Reading voices.",
        "voices": ["守仁"],
        "duration_s": 10.0,
    }
    built = sr.build_h3_prompt(
        plan, strict=True,
        reference_files={1: scene_pic, 2: angle_pic, 3: shouren_pic})
    assert built["dialogue_speakers"] == ["守仁"]
    assert "守仁 (S1) 说，<d>我想做圣贤。</d>" in built["text"]
    assert sr.check_h3_prompt(built)["verdict"] == "pass"
    assert built["picture_files"][3] == shouren_pic["file"]
    assert built["frames"] == 243


def test_scene_strict_bare_angle_string_fails(tmp_path: Path) -> None:
    scene_pic = _pic(tmp_path, "scene.png")
    plan = {
        "scene": {"description": "A quiet schoolroom."},
        "characters": [],
        "angles": ["The same room from the doorway."],
        "shots": [{"description": "Rain falls."}],
        "soundscape": "Rain.",
        "voices": [],
        "duration_s": 10.0,
    }
    with pytest.raises(CapabilityError, match="bare string"):
        sr.build_h3_prompt(plan, strict=True, reference_files={1: scene_pic})


def test_scene_dialogue_without_voice_fails(tmp_path: Path) -> None:
    scene_pic = _pic(tmp_path, "scene.png")
    plan = {
        "scene": {"description": "A quiet schoolroom."},
        "characters": [],
        "angles": [],
        "shots": [{"description": "守仁走进私塾。",
                   "dialogue": "守仁说：\"我想做圣贤。\""}],
        "soundscape": "Reading voices.",
        "voices": [],
        "duration_s": 10.0,
    }
    with pytest.raises(CapabilityError, match="no declared voice"):
        sr.build_h3_prompt(plan, strict=True, reference_files={1: scene_pic})


def test_check_h3_prompt_unnumbered_dialogue_fails() -> None:
    built = sr.build_h3_prompt({
        "scene": {"description": "A quiet tea room."},
        "characters": [],
        "angles": [],
        "shots": [{"description": "Mei pours tea. Mei says: \"The rain has not stopped.\""}],
        "soundscape": "Rain.",
        "voices": ["Mei"],
    })
    # Rewriting numbers the speaker, so the built prompt passes; strip
    # the tag to simulate an unrewritten prompt reaching the judge.
    tampered = copy.deepcopy(built)
    tampered["sections"]["detailed_description"] = tampered["sections"]["detailed_description"].replace(
        "Mei (S1) says, <d>The rain has not stopped.</d>",
        "Mei says: \"The rain has not stopped.\"")
    tampered["text"] = "\n\n".join(
        f"{name}:\n{tampered['sections'][name]}" for name in sr.H3_SECTIONS)
    result = sr.check_h3_prompt(tampered)
    assert result["verdict"] == "fail"
    assert any(i["code"] == "DIALOGUE_UNNUMBERED" for i in result["issues"])


# ------------------------------------------------------------------ single-entry note


def test_avcraft_renderer_is_marked_legacy() -> None:
    from hevi.avcraft.oskill import shotprompt

    assert "LEGACY" in shotprompt.__doc__
    assert "LEGACY" in shotprompt.compile_shot_prompt.__doc__
