"""New optional fields for story.prompt_compiler (2026-10-28).

Covers, without loosening any of the five existing gates:

1. shot-level ``negative_prompts`` (deduped list -> [负面清单]);
2. camera ``easing`` (closed list) + ``shot_size_end`` (framing
   transition rendered in the [机位] line);
3. shot-level ``fallbacks`` (trigger + replacement -> [备选方案],
   kept out of the main prompt body).

Garden fixture: a 10-second vertical one-take in a Suzhou-style
garden, modelled on the user's reference prompt (still 0-2.5s,
slow push 2.5-4.5s from 中景 to 中近景, petal catch, speaking,
smile close). Two deliberate deviations from the reference prompt,
both forced by the *unchanged* gates and documented here rather than
hidden: the reference 11-character line spoken in 3.0s needs 4.55s
under the unchanged gate-2 estimator (11 chars / 4 per second +
0.4s punctuation + 1.0s margin), so the passing fixture speaks the
4-character line "玉兰开了" (needs 2.0s) in its 2.8s beat; and the
catch beat is 4.5-5.5s (not 4.5-5.3s) because beats must be >= 1.0s.
Neither deviation touches gate logic.
"""

import copy

import pytest

from hevi.capabilities.prompt_compiler import (
    PromptCompilerError,
    compile_clip_prompts,
    compile_episode,
    compile_shot_prompt,
)


def _state():
    return {
        "人物": {"脸": "与参考图一致", "发簪": "金色花朵发簪在位"},
        "服装": {"裙": "象牙白缎面抹胸长裙", "披帛": "米白纱质披帛搭在手肘"},
        "道具": {"左手": "轻轻搭在月洞门石边沿"},
    }


def garden_episode():
    return {
        "episode_no": "GARDEN",
        "title": "玉兰开了",
        "target_duration_s": 10.0,
        "aspect": "9:16",
        "style": "小红书新中式写真风格，奶白色调，低饱和，柔焦",
        "reference": "首帧图（已裁成 9:16）",
        "shots": [
            {
                "shot_no": "G01",
                "scene": "苏州园林风格中式古典园林，白墙圆形月洞门，门洞里有亭子、太湖石假山和碧绿池水",
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
                "characters": ["二十多岁女子"],
                "props": ["金色花朵发簪", "金色细长耳坠"],
                "continuity": {"entry_state": _state(), "exit_state": _state()},
                "negative_prompts": [
                    "换脸",
                    "发簪消失",
                    "手指畸形",
                    "花瓣穿过手掌",
                    "换脸",
                ],
                "fallbacks": [
                    {
                        "trigger": "接花瓣失败或花瓣穿过手掌",
                        "replacement": "抬起画面右侧那只手，把耳边的碎发轻轻别到耳后，并删掉递花瓣动作",
                    },
                    {
                        "trigger": "不想要说话版本",
                        "replacement": "删掉台词，改成低头看一眼掌心的花瓣，再抬眼对镜头笑，背景音乐全程不压低",
                    },
                ],
                "beats": [
                    {
                        "beat_no": 1,
                        "t_start_s": 0.0,
                        "t_end_s": 2.5,
                        "action": "微风吹过，玉兰枝摇动，花瓣飘落，人物看着镜头",
                        "sound": "风声、树叶沙沙声",
                    },
                    {
                        "beat_no": 2,
                        "t_start_s": 2.5,
                        "t_end_s": 4.5,
                        "action": "人物把头轻轻转向画面左侧看向池水和亭子，再慢慢转回来看向镜头",
                        "sound": "风声、鸟叫",
                        "camera_move": "dolly_in",
                    },
                    {
                        "beat_no": 3,
                        "t_start_s": 4.5,
                        "t_end_s": 5.5,
                        "action": "一片玉兰花瓣飘到身前，抬起画面右侧那只手掌心向上接住花瓣",
                        "sound": "风声",
                    },
                    {
                        "beat_no": 4,
                        "t_start_s": 5.5,
                        "t_end_s": 8.3,
                        "action": "看着镜头轻声说话，说到一起来看时把掌心花瓣轻轻往镜头方向递了一下",
                        "sound": "古筝加竹笛，说话时音乐压低",
                        "line": "玉兰开了",
                        "speaker": "女子",
                        "line_mode": "dialogue",
                    },
                    {
                        "beat_no": 5,
                        "t_start_s": 8.3,
                        "t_end_s": 10.0,
                        "action": "轻轻歪头温柔地笑，微风又吹落几片花瓣，保持微笑定格",
                        "sound": "古筝加竹笛、风声",
                    },
                ],
                "clips": [
                    {"clip_id": "G01c1", "beats": [1, 2, 3, 4, 5]},
                ],
            }
        ],
    }


def test_garden_fixture_compiles_and_renders_new_sections():
    episode = garden_episode()
    result = compile_episode(episode)
    prompt = result["prompts"][0]["prompt"]
    assert "[机位]中景→中近景" in prompt
    assert "缓动：起步慢、中段稍快、落定慢（ease_in_out）" in prompt
    assert "[负面清单]" in prompt
    for item in ("换脸", "发簪消失", "手指畸形", "花瓣穿过手掌"):
        assert item in prompt
    # Dedupe: the duplicated negative appears exactly once in its section.
    section = prompt.split("[负面清单]", 1)[1].split("[备选方案]", 1)[0]
    assert section.count("换脸") == 1
    assert "[备选方案]" in prompt
    assert "触发：接花瓣失败或花瓣穿过手掌" in prompt
    assert "改成：抬起画面右侧那只手，把耳边的碎发轻轻别到耳后" in prompt
    assert "触发：不想要说话版本" in prompt
    # Section order: negative, then fallbacks, then constraints.
    assert (
        prompt.index("[负面清单]")
        < prompt.index("[备选方案]")
        < prompt.index("[约束]")
    )
    # Fallbacks stay out of the main body: the replacement text must
    # not appear before the [备选方案] section.
    main_body = prompt.split("[备选方案]", 1)[0]
    assert "别到耳后" not in main_body
    assert "低头看一眼掌心的花瓣" not in main_body


def test_new_fields_in_json_and_clip_prompts():
    episode = garden_episode()
    result = compile_episode(episode)
    entry = result["prompts"][0]
    assert entry["negative_prompts"] == [
        "换脸",
        "发簪消失",
        "手指畸形",
        "花瓣穿过手掌",
    ]
    assert entry["easing"] == "ease_in_out"
    assert entry["shot_size_end"] == "中近景"
    assert entry["fallbacks"][0]["trigger"] == "接花瓣失败或花瓣穿过手掌"
    assert entry["fallbacks"][1]["replacement"].startswith("删掉台词")
    clips = compile_clip_prompts(episode)
    clip = clips["G01c1"]
    assert "Easing: ease_in_out" in clip
    assert "Framing transition: 中景→中近景" in clip
    assert "Negative list: 换脸; 发簪消失; 手指畸形; 花瓣穿过手掌" in clip
    assert "Fallbacks: 接花瓣失败或花瓣穿过手掌 => " in clip
    assert "不想要说话版本 => 删掉台词" in clip


def test_illegal_easing_fails_naming_shot():
    episode = garden_episode()
    episode["shots"][0]["camera"]["easing"] = "bounce"
    with pytest.raises(PromptCompilerError, match="easing"):
        compile_episode(episode)


def test_illegal_shot_size_end_fails():
    episode = garden_episode()
    episode["shots"][0]["camera"]["shot_size_end"] = "超大全景"
    with pytest.raises(PromptCompilerError, match="shot_size_end"):
        compile_episode(episode)


def test_empty_negative_entry_fails():
    episode = garden_episode()
    episode["shots"][0]["negative_prompts"] = ["换脸", "   "]
    with pytest.raises(PromptCompilerError, match="negative_prompts"):
        compile_episode(episode)


def test_non_string_negative_entry_fails():
    episode = garden_episode()
    episode["shots"][0]["negative_prompts"] = ["换脸", 42]
    with pytest.raises(PromptCompilerError, match="negative_prompts"):
        compile_episode(episode)


def test_fallback_missing_replacement_fails():
    episode = garden_episode()
    episode["shots"][0]["fallbacks"] = [{"trigger": "接不住"}]
    with pytest.raises(PromptCompilerError, match="fallback"):
        compile_episode(episode)


def test_fallback_missing_trigger_fails():
    episode = garden_episode()
    episode["shots"][0]["fallbacks"] = [{"replacement": "别碎发"}]
    with pytest.raises(PromptCompilerError, match="fallback"):
        compile_episode(episode)


def test_fallback_empty_trigger_fails():
    episode = garden_episode()
    episode["shots"][0]["fallbacks"] = [
        {"trigger": "  ", "replacement": "别碎发"}
    ]
    with pytest.raises(PromptCompilerError, match="fallback"):
        compile_episode(episode)


def test_unfilled_fields_leave_old_output_unchanged():
    episode = garden_episode()
    shot = episode["shots"][0]
    for key in ("negative_prompts", "fallbacks"):
        shot.pop(key, None)
    shot["camera"].pop("easing", None)
    shot["camera"].pop("shot_size_end", None)
    result = compile_episode(episode)
    prompt = result["prompts"][0]["prompt"]
    assert "[机位]" not in prompt
    assert "[负面清单]" not in prompt
    assert "[备选方案]" not in prompt
    assert prompt.rstrip().endswith(
        "镜头之间禁叠化、禁交叉溶解、禁淡入淡出。"
    )
    entry = result["prompts"][0]
    assert entry["negative_prompts"] == []
    assert entry["fallbacks"] == []
    assert entry["easing"] is None
    assert entry["shot_size_end"] is None
    clips = compile_clip_prompts(episode)
    assert "Negative list" not in clips["G01c1"]
    assert "Fallbacks" not in clips["G01c1"]
    assert "Easing" not in clips["G01c1"]
    assert "Framing transition" not in clips["G01c1"]


def test_same_size_end_produces_no_transition_arrow():
    episode = garden_episode()
    shot = episode["shots"][0]
    shot["camera"]["shot_size_end"] = "中景"
    shot["camera"].pop("easing", None)
    prompt = compile_shot_prompt(episode, shot)
    assert "中景→中景" not in prompt
    assert "[机位]" not in prompt


def test_easing_only_renders_camera_line_without_transition():
    episode = garden_episode()
    shot = episode["shots"][0]
    shot["camera"].pop("shot_size_end", None)
    shot["camera"]["easing"] = "hold"
    prompt = compile_shot_prompt(episode, shot)
    assert "[机位]" in prompt
    assert "缓动：保持不动（hold）" in prompt
    assert "→" not in prompt.split("[机位]", 1)[1].split("\n", 1)[0]


def test_empty_negative_list_equals_unfilled():
    episode = garden_episode()
    episode["shots"][0]["negative_prompts"] = []
    episode["shots"][0]["fallbacks"] = []
    prompt = compile_shot_prompt(episode, episode["shots"][0])
    assert "[负面清单]" not in prompt
    assert "[备选方案]" not in prompt


def test_old_format_prompt_unchanged_for_plain_shot():
    # A minimal shot with none of the new fields must not gain sections.
    plain = copy.deepcopy(garden_episode())
    shot = plain["shots"][0]
    for key in ("negative_prompts", "fallbacks"):
        shot.pop(key, None)
    shot["camera"].pop("easing", None)
    shot["camera"].pop("shot_size_end", None)
    shot.pop("clips", None)
    prompt = compile_shot_prompt(plain, shot)
    for section in ("[机位]", "[负面清单]", "[备选方案]"):
        assert section not in prompt
    assert "[约束]" in prompt
