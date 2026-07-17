"""SPEC-003 ⑤ 通鉴对白+口型后端桥接的确定性转换测试(无 LLM/无生成/无花费)。"""

from __future__ import annotations

from types import SimpleNamespace

from hevi.director.pipeline_schemas import (
    Concept,
    DesignCharacter,
    DesignList,
    DesignScene,
    ShotBlocking,
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
    # 旁白行不进配音轨:script.lines 只剩两句对白(旁白不配音)
    assert [(ln.speaker, ln.text) for ln in script.lines] == [
        ("智伯", "把地给我。"),
        ("韩康子", "不给。"),
    ]
    assert all(ln.type == "dialogue" for ln in script.lines)
    # 但非对白镜头保留为静默动作/建场镜头:第 1 镜=对白镜头,第 2 镜(纯旁白+空镜)=动作镜头
    assert len(shotlist.shots) == 2
    sh = shotlist.shots[0]
    assert sh.line_ids == [script.lines[0].line_id, script.lines[1].line_id]  # 对白镜头
    assert sh.characters == ["智伯", "韩康子"]
    assert sh.camera.shot_size == "medium_close"  # "近景" → medium_close
    action = shotlist.shots[1]  # 静默动作镜头:无对白 line,靠 visual_prompt 生成
    assert action.line_ids == []
    assert action.visual_prompt == "纯旁白空镜"
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
    assert len(filled.shots) == 2
    assert filled.shots[0].t_start_ms == 0
    assert filled.shots[0].t_end_ms == 2800  # 对白镜:覆盖两条 line 的最小起点/最大终点
    # 静默动作镜(无音频段):接在对白镜后,名义 4s,不被丢
    assert filled.shots[1].t_start_ms == 2800
    assert filled.shots[1].t_end_ms == 2800 + 4000


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


def test_incomplete_state_suffix_reaction_chain():
    """INC-001 §C:连续反应链动词 → 关键帧加"未完成态"约束;平铺动作不加。"""
    from hevi.tongjian.scene_render_avatar import _incomplete_state_suffix

    assert _incomplete_state_suffix("豫让突然拔出匕首")  # "突然/拔" → 未完成态
    assert _incomplete_state_suffix("她回头看向门口")  # "回头"
    assert _incomplete_state_suffix("侍卫一把拽住他胳膊")  # "一把/拽"
    assert not _incomplete_state_suffix("两人平静地对坐饮茶")  # 无反应链动词
    assert not _incomplete_state_suffix("")


def test_build_tongjian_inputs_passes_action_beats_to_shot():
    """INC-001 §B:ShotListItem.action_beats 确定性透传到通鉴 Shot.action_beats(供 L6 kf2v)。"""
    shot_list = ShotList(
        shots=[
            ShotListItem(
                shot_id="SH001",
                scene_no=1,
                visual_prompt="张飞拔剑自刎",
                action_beats=["张飞猛地抽剑架颈", "刘备扑上夺剑", "宝剑坠地紧抱"],
                dialogue_lines=[ShotListDialogueLine(character_name="刘备", text="三弟不可!")],
                character_names=["张飞", "刘备"],
                scene_name="军帐",
            )
        ]
    )
    design_list = DesignList(
        characters=[DesignCharacter(name="张飞"), DesignCharacter(name="刘备")],
        scenes=[DesignScene(name="军帐")],
    )
    _, shotlist, _ = build_tongjian_inputs(
        shot_list=shot_list,
        design_list=design_list,
        concept=Concept(),
        voice_by_speaker={},
    )
    assert shotlist.shots[0].action_beats == ["张飞猛地抽剑架颈", "刘备扑上夺剑", "宝剑坠地紧抱"]


def test_build_tongjian_inputs_passes_blocking_to_shot():
    """走位透传:ShotListItem.blocking 格式化成"角色:位置,朝向"喂给 L6 多角色关键帧;
    未锁定角色的走位丢弃(治"走位乱七八糟"——此前 blocking 在桥接层被整个丢掉)。"""
    shot_list = ShotList(
        shots=[
            ShotListItem(
                shot_id="SH001",
                scene_no=1,
                visual_prompt="张飞跪地,刘备关羽立于案后",
                blocking=[
                    ShotBlocking(character_name="张飞", position="画面左侧", facing="刘备"),
                    ShotBlocking(character_name="刘备", position="画面中央"),
                    ShotBlocking(character_name="路人", position="画面右", facing="张飞"),
                ],
                character_names=["张飞", "刘备"],
                scene_name="军帐",
            )
        ]
    )
    design_list = DesignList(
        characters=[DesignCharacter(name="张飞"), DesignCharacter(name="刘备")],
        scenes=[DesignScene(name="军帐")],
    )
    _, shotlist, _ = build_tongjian_inputs(
        shot_list=shot_list,
        design_list=design_list,
        concept=Concept(),
        voice_by_speaker={},
    )
    # 未锁定的"路人"被丢;锁定角色格式化为"名:位置[,面向X]"
    assert shotlist.shots[0].blocking == ["张飞:画面左侧,面向刘备", "刘备:画面中央"]


def test_build_tongjian_inputs_threads_valid_target_drops_invalid():
    """INC-001 §H:受话对象是已锁定角色且非说话人本人 → 写入 ScriptLine.target;
    未锁定名/自指 → 丢成空串(不污染 eyeline)。"""
    shot_list = ShotList(
        shots=[
            ShotListItem(
                shot_id="SH001",
                scene_no=1,
                dialogue_lines=[
                    ShotListDialogueLine(
                        character_name="智伯", text="把地给我。", target_name="韩康子"
                    ),
                    ShotListDialogueLine(
                        character_name="韩康子", text="不给。", target_name="路人甲"
                    ),
                    ShotListDialogueLine(character_name="智伯", text="哼。", target_name="智伯"),
                ],
                character_names=["智伯", "韩康子"],
                scene_name="宫殿",
            )
        ]
    )
    design_list = DesignList(
        characters=[DesignCharacter(name="智伯"), DesignCharacter(name="韩康子")],
        scenes=[DesignScene(name="宫殿")],
    )
    script, _, _ = build_tongjian_inputs(
        shot_list=shot_list, design_list=design_list, concept=Concept(), voice_by_speaker={}
    )
    by_speaker_text = {(ln.speaker, ln.text): ln.target for ln in script.lines}
    assert by_speaker_text[("智伯", "把地给我。")] == "韩康子"  # 有效受话人
    assert by_speaker_text[("韩康子", "不给。")] == ""  # 未锁定名 → 丢
    assert by_speaker_text[("智伯", "哼。")] == ""  # 自指 → 丢
