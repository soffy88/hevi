"""SPEC-003 + 3O §2 Task 2.1:apply_locked_storyboard_override 纯函数单测。

该函数是 SPEC 要求的确定性分镜覆盖算法(stateless),抽离自
longvideo_orchestrator.py 的运行期钩子替换,目标上游至 oskill.storyboard_locked_override。
"""

from __future__ import annotations

from hevi.pipeline.storyboard_locked_override import (
    apply_locked_storyboard_override,
    strip_stage_directions,
)


def _locked_shot_list() -> list[dict]:
    return [
        {
            "shot_id": "SH001_01",
            "scene_no": 1,
            "visual_prompt": "二人对峙",
            "dialogue_lines": [
                {"character_name": "智伯", "text": "把地给我。"},
                {"character_name": "韩康子", "text": "不给。"},
            ],
            "duration_s": 6.0,
        },
        {
            "shot_id": "SH002_01",
            "scene_no": 2,
            "visual_prompt": "史官旁白",
            "dialogue_lines": [{"character_name": "", "text": "三家终于罢兵。"}],
            "duration_s": 4.0,
        },
    ]


def test_apply_locked_storyboard_override_deterministic_shape():
    result = apply_locked_storyboard_override(script_data={}, locked_shots=_locked_shot_list())

    assert set(result) == {"chapter_script", "storyboard", "shot_plans"}

    chapter_script = result["chapter_script"]
    # 只保留有说话人的对白行(旁白行 character_name 为空,彻底丢弃,不进配音轨)
    assert len(chapter_script.chapters) == 1
    dialogues = chapter_script.chapters[0].dialogues
    assert [(d.speaker_id, d.text) for d in dialogues] == [
        ("智伯", "把地给我。"),
        ("韩康子", "不给。"),
    ]
    # total_duration_s = 6.0 + 4.0
    assert chapter_script.total_duration_s == 10.0

    # storyboard 为占位(shot_gen_fn 不读其内容)
    assert result["storyboard"].shots == []

    # shot_plans 与锁定镜头数一致;纯旁白镜头保留画面但 tts_text 为空
    plans = result["shot_plans"]
    assert [p.shot_id for p in plans] == ["SH001_01", "SH002_01"]
    assert plans[0].image_prompt == "二人对峙"
    assert plans[0].tts_text == "把地给我。。不给。"  # "。" join 对白行
    assert plans[0].duration_s == 6.0
    assert plans[1].tts_text == ""  # 旁白镜头无台词
    assert plans[1].duration_s == 4.0


def test_apply_locked_storyboard_override_strips_stage_directions():
    locked = [
        {
            "shot_id": "S1",
            "visual_prompt": "p",
            "dialogue_lines": [
                {"character_name": "韩康子", "text": "不给。（拂袖而去）"},
            ],
            "duration_s": 3.0,
        }
    ]
    result = apply_locked_storyboard_override(script_data={}, locked_shots=locked)
    dialogues = result["chapter_script"].chapters[0].dialogues
    assert dialogues[0].text == "不给。"
    assert result["shot_plans"][0].tts_text == "不给。"


def test_apply_locked_storyboard_override_empty_inputs():
    result = apply_locked_storyboard_override(script_data={}, locked_shots=[])
    assert result["chapter_script"].chapters[0].dialogues == []
    assert result["chapter_script"].total_duration_s == 0.0
    assert result["storyboard"].shots == []
    assert result["shot_plans"] == []


def test_strip_stage_directions_both_brackets():
    assert strip_stage_directions("把地给我。（狠狠一拍）") == "把地给我。"
    assert strip_stage_directions("不给。(转身)") == "不给。"
    assert strip_stage_directions("没有括号") == "没有括号"
