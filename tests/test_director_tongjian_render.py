"""SPEC-003 ⑤ 通鉴对白+口型后端桥接的确定性转换测试(无 LLM/无生成/无花费)。"""

from __future__ import annotations

from types import SimpleNamespace

from hevi.director.pipeline_schemas import (
    Concept,
    DesignCharacter,
    DesignList,
    DesignScene,
    EyelineTrack,
    PerformancePhase,
    PerformanceTrack,
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


def test_build_tongjian_inputs_scene_id_matches_long_description_to_design_scene_name():
    """渲染层洞#2(2026-07-18):④分镜层的 scene_name 常是**长描述句**(如"道观山门内侧，朱漆
    斑驳的木门无声向内开启，门轴轻响如叹息"),不是③ DesignScene 的**短名**("道观山门内侧")
    原样。原来的精确匹配(`shot.scene_name in scene_names`)对长句恒假,scene_id 落到长句
    本身——下游 scene_bg_by_id(键是短名)永远查不到,空景板传不进渲染层,真机产物背景是纯灰
    影棚底(真机复验实证)。这里验证:长描述句只要以短名开头/包含短名,scene_id 就该解析成
    短名,能跟 scene_bg_by_id 的键对上。"""
    shot_list = ShotList(
        shots=[
            ShotListItem(
                shot_id="SH001",
                scene_no=1,
                visual_prompt="王生独跪",
                dialogue_lines=[ShotListDialogueLine(character_name="", text="独自等候。")],
                character_names=["王生"],
                scene_name="道观山门内侧，朱漆斑驳的木门无声向内开启，门轴轻响如叹息",
            )
        ]
    )
    design_list = DesignList(
        characters=[DesignCharacter(name="王生")],
        scenes=[DesignScene(name="道观山门内侧"), DesignScene(name="崂山道观山门前")],
    )
    _, shotlist, _ = build_tongjian_inputs(
        shot_list=shot_list,
        design_list=design_list,
        concept=Concept(theme="修道"),
        voice_by_speaker={},
    )
    # scene_id 解析成短名(能对上 scene_bg_by_id 的键),不是原样长句。
    assert shotlist.shots[0].scene_id == "道观山门内侧"


def test_build_tongjian_inputs_scene_id_falls_back_when_no_design_scene_matches():
    """长描述句里一个 DesignScene 短名都不包含时(格式意外),退回原样——不是新的空值行为,
    跟修复前的向后兼容路径一致,不会因为解析不出就报错/丢镜头。"""
    shot_list = ShotList(
        shots=[
            ShotListItem(
                shot_id="SH001",
                scene_no=1,
                visual_prompt="过场",
                dialogue_lines=[ShotListDialogueLine(character_name="", text="过场旁白。")],
                scene_name="完全不相关的一段描述",
            )
        ]
    )
    design_list = DesignList(characters=[], scenes=[DesignScene(name="道观山门内侧")])
    _, shotlist, _ = build_tongjian_inputs(
        shot_list=shot_list,
        design_list=design_list,
        concept=Concept(theme="修道"),
        voice_by_speaker={},
    )
    assert shotlist.shots[0].scene_id == "完全不相关的一段描述"


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


def test_build_tongjian_inputs_compiles_performance_track_to_temporal_prompt():
    """INC-002:performance_track 在桥接层编译成 Shot.temporal_prompt;未填 → 空串(inert)。"""
    track = PerformanceTrack(
        total_duration_s=6.0,
        phases=[
            PerformancePhase(
                phase_id="ph1",
                order=1,
                t_start_s=0.0,
                t_end_s=3.0,
                label="锁定",
                eyeline_track=EyelineTrack(state="locked", direction="center"),
            ),
            PerformancePhase(
                phase_id="ph2",
                order=2,
                t_start_s=3.0,
                t_end_s=6.0,
                label="游离",
                eyeline_track=EyelineTrack(
                    state="breaking", direction="down", transition_speed="quick"
                ),
            ),
        ],
    )
    shot_list = ShotList(
        shots=[
            ShotListItem(
                shot_id="SH001",
                scene_no=1,
                visual_prompt="特写",
                performance_track=track,
                character_names=["张飞"],
                scene_name="军帐",
            ),
            ShotListItem(
                shot_id="SH002",
                scene_no=1,
                visual_prompt="空镜",
                character_names=["张飞"],
                scene_name="军帐",
            ),  # 无 performance_track
        ]
    )
    design_list = DesignList(
        characters=[DesignCharacter(name="张飞")], scenes=[DesignScene(name="军帐")]
    )
    _, shotlist, _ = build_tongjian_inputs(
        shot_list=shot_list, design_list=design_list, concept=Concept(), voice_by_speaker={}
    )
    tp = shotlist.shots[0].temporal_prompt
    assert tp.splitlines()[0].startswith("[0–3s] 锁定 → ") and "视线锁定" in tp
    assert "[3–6s] 游离 → " in tp and "视线开始游离" in tp
    assert shotlist.shots[1].temporal_prompt == ""  # 未填 → inert
    # §1.1 phase→beat 切片也随 Shot 透传(render 消费用):first=锁定段、aftermath=游离段
    by_role = shotlist.shots[0].temporal_by_role
    assert "视线锁定" in by_role["first"] and "视线开始游离" in by_role["aftermath"]
    assert shotlist.shots[1].temporal_by_role == {}  # 未填 → inert


def test_build_tongjian_inputs_derives_negatives_and_audio():
    """INC-002 v0.2:桥接层从 schema 派生 negative_prompt(注入 sdxl)+ audio_prompt;未填 inert。"""
    from hevi.director.pipeline_schemas import (
        FacialPerformance,
        FacialPhysiology,
        PropPerformance,
    )

    track = PerformanceTrack(
        total_duration_s=3.0,
        phases=[
            PerformancePhase(
                phase_id="ph1",
                order=1,
                t_start_s=0.0,
                t_end_s=3.0,
                prop_performance=[PropPerformance(prop_type="firearm", material="metal")],
                facial_performance=FacialPerformance(physiology=FacialPhysiology(swallow=True)),
            )
        ],
    )
    shot_list = ShotList(
        shots=[
            ShotListItem(
                shot_id="SH001",
                scene_no=1,
                visual_prompt="举枪",
                performance_track=track,
                character_names=["刺客"],
                scene_name="厕所",
            ),
            ShotListItem(
                shot_id="SH002",
                scene_no=1,
                visual_prompt="空镜",
                character_names=["刺客"],
                scene_name="厕所",
            ),  # 无 INC-002 → inert
        ]
    )
    design_list = DesignList(
        characters=[DesignCharacter(name="刺客")], scenes=[DesignScene(name="厕所")]
    )
    _, shotlist, _ = build_tongjian_inputs(
        shot_list=shot_list, design_list=design_list, concept=Concept(), voice_by_speaker={}
    )
    neg = shotlist.shots[0].negative_prompt
    assert "不要多余或畸形的手指" in neg and "不要枪械结构变形" in neg  # 有枪+手自动派生
    assert "吞咽" in shotlist.shots[0].audio_prompt  # 喉结吞咽自动派生进声音层
    assert shotlist.shots[1].negative_prompt == "" and shotlist.shots[1].audio_prompt == ""  # inert


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
