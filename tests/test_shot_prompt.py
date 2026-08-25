"""shot_prompt 测试 —— 五层英文镜头提示词(OpenMontage shot_prompt_builder 内化)。

覆盖: 单场景五层拼接 / 空层跳过 / 批量 / 转场跳过 / style_context 提取。
"""

from __future__ import annotations

from hevi.studio.shot_prompt import build_batch_prompts, build_shot_prompt


def test_build_shot_prompt_full_layers() -> None:
    scene = {
        "id": "s1",
        "description": "A lone lighthouse on a rocky cliff",
        "texture_keywords": ["rusty railing", "sea spray"],
        "shot_language": {
            "lens_mm": 35,
            "depth_of_field": "shallow",
            "shot_size": "wide",
            "camera_movement": "dolly_in",
            "lighting_key": "golden_hour",
            "color_temperature": "warm",
        },
    }
    style = {"mood": "melancholic", "visual_language": {"aesthetic": "cinematic realism"}}
    prompt = build_shot_prompt(scene, style)

    assert "35mm lens" in prompt
    assert "shallow depth of field" in prompt
    assert "wide shot" in prompt
    assert "dolly in" in prompt
    assert "lone lighthouse" in prompt
    assert "rusty railing, sea spray" in prompt
    assert "golden hour" in prompt
    assert "warm amber-toned" in prompt
    assert "Style: cinematic realism" in prompt


def test_build_shot_prompt_skips_empty_layers() -> None:
    scene = {"description": "A desk with a notebook"}
    prompt = build_shot_prompt(scene)
    # 无 shot_language → 只有 subject 层
    assert "desk with a notebook" in prompt
    assert "lens" not in prompt
    assert "Style:" not in prompt


def test_build_shot_prompt_movement_static_omitted() -> None:
    scene = {
        "description": "An empty hallway",
        "shot_language": {"shot_size": "medium", "camera_movement": "static"},
    }
    prompt = build_shot_prompt(scene)
    assert "medium shot" in prompt
    assert "locked-off static camera" not in prompt  # static 被省略


def test_build_shot_prompt_unknown_enum_passthrough() -> None:
    scene = {
        "description": "A room",
        "shot_language": {"shot_size": "macro", "lighting_key": "candlelight"},
    }
    prompt = build_shot_prompt(scene)
    assert "macro" in prompt
    assert "candlelight" in prompt


def test_build_batch_prompts_skips_transitions() -> None:
    scenes = [
        {"id": "s1", "type": "video", "description": "Scene one"},
        {"id": "s2", "type": "transition", "description": "Wipe to next"},
        {"id": "s3", "type": "video", "description": "Scene three", "hero_moment": True},
    ]
    results = build_batch_prompts(scenes)
    assert [r["scene_id"] for r in results] == ["s1", "s3"]
    assert results[1]["hero_moment"] is True
    assert all(r["prompt"] for r in results)


def test_build_shot_prompt_no_style_context() -> None:
    scene = {"id": "x", "description": "A forest path"}
    prompt = build_shot_prompt(scene, None)
    assert "forest path" in prompt
    assert "Style:" not in prompt
