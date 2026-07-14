"""SPEC-003 ⑤ 通鉴对白+口型后端桥接的确定性转换测试(无 LLM/无生成/无花费)。"""

from __future__ import annotations

from types import SimpleNamespace

from hevi.director.pipeline_schemas import (
    Concept,
    DesignCharacter,
    DesignList,
    DesignScene,
    ShotList,
    ShotListDialogueLine,
    ShotListItem,
)
from hevi.director.tongjian_render import (
    _build_constitution,
    _fill_shot_timings,
    build_tongjian_inputs,
)


def _shot_list() -> ShotList:
    return ShotList(
        shots=[
            ShotListItem(
                shot_id="SH001_01",
                scene_no=1,
                shot_size="近景",
                visual_prompt="宫室对峙",
                dialogue_lines=[
                    ShotListDialogueLine(character_name="", text="旁白:多年以后。"),  # 旁白丢弃
                    ShotListDialogueLine(character_name="智伯", text="把地给我。"),
                    ShotListDialogueLine(character_name="韩康子", text="不给。"),
                ],
                character_names=["智伯", "韩康子"],
                scene_name="宫室",
            ),
            ShotListItem(
                shot_id="SH002_01",
                scene_no=2,
                visual_prompt="纯旁白空镜",
                dialogue_lines=[ShotListDialogueLine(character_name="", text="三家罢兵。")],
                scene_name="城外",
            ),
        ]
    )


def _design_list() -> DesignList:
    return DesignList(
        characters=[
            DesignCharacter(name="智伯", appearance="魁梧", wardrobe="锦袍"),
            DesignCharacter(name="韩康子"),
        ],
        scenes=[DesignScene(name="宫室")],
    )


def test_build_tongjian_inputs_drops_narration_and_maps_dialogue():
    script, shotlist, bible = build_tongjian_inputs(
        shot_list=_shot_list(),
        design_list=_design_list(),
        concept=Concept(theme="索地", tone="压抑"),
        voice_by_speaker={"智伯": "zh_male_deep", "韩康子": "zh_male_standard"},
    )
    # 旁白两行都被丢:只剩两句对白
    assert [(ln.speaker, ln.text) for ln in script.lines] == [
        ("智伯", "把地给我。"),
        ("韩康子", "不给。"),
    ]
    assert all(ln.type == "dialogue" for ln in script.lines)
    # 纯旁白的第 2 镜整个丢弃 → 只剩 1 个镜头,引用两条对白 line
    assert len(shotlist.shots) == 1
    sh = shotlist.shots[0]
    assert sh.line_ids == [script.lines[0].line_id, script.lines[1].line_id]
    assert sh.characters == ["智伯", "韩康子"]
    assert sh.camera.shot_size == "medium_close"  # "近景" → medium_close
    # CharacterBible:每角色带分配的音色
    voices = {e.character_id: e.voice_id for e in bible.characters}
    assert voices == {"智伯": "zh_male_deep", "韩康子": "zh_male_standard"}
    assert next(e for e in bible.characters if e.character_id == "智伯").appearance == "魁梧 锦袍"


def test_fill_shot_timings_from_timeline():
    _, shotlist, _ = build_tongjian_inputs(
        shot_list=_shot_list(),
        design_list=_design_list(),
        concept=Concept(theme="索地"),
        voice_by_speaker={},
    )
    lid0, lid1 = shotlist.shots[0].line_ids
    timeline = SimpleNamespace(
        audio_segments=[
            SimpleNamespace(line_id=lid0, t_start_ms=0, t_end_ms=1500),
            SimpleNamespace(line_id=lid1, t_start_ms=1500, t_end_ms=2800),
        ]
    )
    filled = _fill_shot_timings(shotlist, timeline)
    assert filled.shots[0].t_start_ms == 0
    assert filled.shots[0].t_end_ms == 2800  # 覆盖该镜两条 line 的最小起点/最大终点


def test_constitution_carries_concept_and_aspect():
    c = _build_constitution(
        Concept(theme="索地", tone="压抑", style="水墨"),
        aspect_ratio="9:16",
        target_duration_sec=120,
    )
    assert c.logline == "索地"
    assert c.tone == ["压抑"]
    assert c.visual_style.aspect_ratio == "9:16"
    assert c.visual_style.art_direction == "水墨"
    assert c.target_duration_sec == 120
