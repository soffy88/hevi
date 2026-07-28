"""SPEC-003 ①-④ 草稿生成函数测试(concept/screenplay/design_list/shot_list)。"""

from __future__ import annotations

from unittest.mock import AsyncMock

from hevi.director.concept import generate_concept_draft
from hevi.director.design_list import generate_design_list_draft
from hevi.director.pipeline_schemas import (
    Concept,
    DesignCharacter,
    DesignList,
    DesignScene,
    Screenplay,
    ScreenplayDialogueLine,
    ScreenplayScene,
    ShotBlocking,
)
from hevi.director.screenplay import generate_screenplay_draft
from hevi.director.shot_list import classify_quality_tier, generate_shot_list_draft


def _llm(content: str) -> AsyncMock:
    return AsyncMock(return_value={"content": content})


# ── ① Concept ─────────────────────────────────────────────────────────────


async def test_concept_draft_parses_llm_json():
    llm = _llm(
        '{"theme": "权臣索地", "tone": "压抑蓄力", "style": "电影感", '
        '"target_audience": "历史剧爱好者", "duration_archetype": "1-5min", '
        '"quality_bar": "精品慢工"}'
    )
    c = await generate_concept_draft(material_text="智伯求地于韩康子", llm=llm)
    assert c.theme == "权臣索地"
    assert c.duration_archetype == "1-5min"


async def test_concept_draft_invalid_archetype_falls_back():
    llm = _llm('{"theme": "x", "duration_archetype": "不存在的档位"}')
    c = await generate_concept_draft(material_text="素材", llm=llm)
    assert c.duration_archetype == "1-5min"


async def test_concept_draft_llm_failure_returns_defaults():
    llm = AsyncMock(side_effect=RuntimeError("llm down"))
    c = await generate_concept_draft(material_text="素材", llm=llm)
    assert c == Concept()


# ── ② Screenplay ──────────────────────────────────────────────────────────


async def test_screenplay_draft_parses_scenes_and_dialogue():
    llm = _llm(
        '{"scenes": [{"scene_no": 1, "location": "宫殿", '
        '"characters_present": ["智伯", "韩康子"], "narration": "智伯设宴。", '
        '"dialogue": [{"character_name": "智伯", "text": "把地给我。"}], '
        '"event_summary": "索地"}]}'
    )
    concept = Concept(theme="权臣索地")
    sp = await generate_screenplay_draft(concept=concept, material_text="智伯求地", llm=llm)
    assert len(sp.scenes) == 1
    assert sp.scenes[0].dialogue[0].character_name == "智伯"
    assert sp.scenes[0].dialogue[0].text == "把地给我。"


async def test_screenplay_draft_llm_failure_falls_back_to_single_scene():
    llm = AsyncMock(side_effect=RuntimeError("llm down"))
    sp = await generate_screenplay_draft(concept=Concept(), material_text="原文素材", llm=llm)
    assert len(sp.scenes) == 1
    assert sp.scenes[0].narration == "原文素材"


async def test_screenplay_draft_caps_scenes_when_configured(monkeypatch):
    """settings.director_max_scenes 设正整数 → 只取前 N 场(测试小规模验证);None/0 = 全量。"""
    from hevi.core.config import settings

    five = (
        '{"scenes": ['
        + ",".join(f'{{"scene_no": {i}, "narration": "第{i}场"}}' for i in range(1, 6))
        + "]}"
    )
    llm = _llm(five)
    monkeypatch.setattr(settings, "director_max_scenes", 2)
    sp = await generate_screenplay_draft(concept=Concept(), material_text="x", llm=llm)
    assert len(sp.scenes) == 2
    monkeypatch.setattr(settings, "director_max_scenes", None)
    sp_full = await generate_screenplay_draft(concept=Concept(), material_text="x", llm=llm)
    assert len(sp_full.scenes) == 5


async def test_screenplay_draft_drops_empty_dialogue_text():
    llm = _llm(
        '{"scenes": [{"scene_no": 1, "dialogue": [{"character_name": "甲", "text": ""}, '
        '{"character_name": "乙", "text": "真台词"}]}]}'
    )
    sp = await generate_screenplay_draft(concept=Concept(), material_text="x", llm=llm)
    assert len(sp.scenes[0].dialogue) == 1
    assert sp.scenes[0].dialogue[0].character_name == "乙"


# ── ③ DesignList ──────────────────────────────────────────────────────────


async def test_design_list_draft_parses_three_lists():
    llm = _llm(
        '{"characters": [{"name": "智伯", "appearance": "面容威严", "is_lead": true}], '
        '"scenes": [{"name": "宫殿", "environment": "朝堂", "is_primary": true}], '
        '"props": [{"name": "玉玦", "appearance": "青玉"}]}'
    )
    screenplay = Screenplay(
        scenes=[ScreenplayScene(scene_no=1, location="宫殿", characters_present=["智伯"])]
    )
    dl = await generate_design_list_draft(screenplay=screenplay, llm=llm)
    assert dl.characters[0].name == "智伯"
    assert dl.characters[0].is_lead is True
    assert dl.scenes[0].name == "宫殿"
    assert dl.props[0].name == "玉玦"


async def test_design_list_draft_llm_failure_falls_back_to_screenplay_extraction():
    """LLM 失败 → 从剧本 characters_present/location 确定性兜底提取(不整体失败)。"""
    llm = AsyncMock(side_effect=RuntimeError("llm down"))
    screenplay = Screenplay(
        scenes=[
            ScreenplayScene(scene_no=1, location="宫殿", characters_present=["智伯", "韩康子"]),
            ScreenplayScene(scene_no=2, location="宫殿", characters_present=["智伯"]),  # 去重
        ]
    )
    dl = await generate_design_list_draft(screenplay=screenplay, llm=llm)
    assert {c.name for c in dl.characters} == {"智伯", "韩康子"}
    assert [s.name for s in dl.scenes] == ["宫殿"]  # 去重


# ── ④ ShotList ────────────────────────────────────────────────────────────


async def test_shot_list_draft_tags_speaker_on_dialogue_lines():
    """治"只有旁白没对白":多角色对话镜头,产出的台词行各自带正确 character_name。"""
    llm = _llm(
        '{"shots": [{"shot_size": "中景", "visual_prompt": "二人对峙", '
        '"dialogue_lines": [{"character_name": "智伯", "text": "把地给我。"}, '
        '{"character_name": "韩康子", "text": "不给。"}], '
        '"character_names": ["智伯", "韩康子"], "duration_s": 6}]}'
    )
    screenplay = Screenplay(
        scenes=[
            ScreenplayScene(
                scene_no=1,
                location="宫殿",
                characters_present=["智伯", "韩康子"],
                dialogue=[
                    ScreenplayDialogueLine(character_name="智伯", text="把地给我。"),
                    ScreenplayDialogueLine(character_name="韩康子", text="不给。"),
                ],
            )
        ]
    )
    design_list = DesignList(
        characters=[DesignCharacter(name="智伯"), DesignCharacter(name="韩康子")],
        scenes=[DesignScene(name="宫殿")],
    )
    sl = await generate_shot_list_draft(screenplay=screenplay, design_list=design_list, llm=llm)
    assert len(sl.shots) == 1
    speakers = [d.character_name for d in sl.shots[0].dialogue_lines]
    assert speakers == ["智伯", "韩康子"]


async def test_shot_list_draft_llm_failure_falls_back_per_scene():
    """单场 LLM 失败只退化那一场(整场一镜),不拖垮全片其余场次。"""

    async def flaky_llm(*, messages, **kw):
        text = messages[0]["content"]
        if "第2场" in text:
            raise RuntimeError("llm down for scene 2")
        return {
            "content": '{"shots": [{"visual_prompt": "v", "dialogue_lines": [], '
            '"character_names": [], "duration_s": 5}]}'
        }

    screenplay = Screenplay(
        scenes=[
            ScreenplayScene(scene_no=1, location="宫殿", narration="第一场"),
            ScreenplayScene(scene_no=2, location="宫殿", narration="第二场旁白"),
        ]
    )
    design_list = DesignList(scenes=[DesignScene(name="宫殿")])
    sl = await generate_shot_list_draft(
        screenplay=screenplay, design_list=design_list, llm=flaky_llm
    )
    # 第一场走真实 LLM 产出 1 镜,第二场兜底也产出 1 镜(旁白行保留)
    assert len(sl.shots) == 2
    scene2_shot = next(s for s in sl.shots if s.scene_no == 2)
    assert scene2_shot.dialogue_lines[0].character_name == ""  # 旁白
    assert scene2_shot.dialogue_lines[0].text == "第二场旁白"


async def test_shot_list_draft_parses_action_beats():
    """INC-001 §B:LLM 产出的 action_beats(有序动作拍点)被解析到 ShotListItem 上;
    空/纯空白拍点被剔除。"""
    llm = _llm(
        '{"shots": [{"shot_size": "全景", "visual_prompt": "张飞拔剑", '
        '"action_beats": ["张飞猛地抽剑架颈", "  ", "刘备扑上夺剑", "宝剑坠地紧抱"], '
        '"dialogue_lines": [], "character_names": ["张飞", "刘备"], "duration_s": 5}]}'
    )
    screenplay = Screenplay(
        scenes=[
            ScreenplayScene(
                scene_no=1, location="军帐", characters_present=["张飞", "刘备"], narration="拔剑"
            )
        ]
    )
    design_list = DesignList(
        characters=[DesignCharacter(name="张飞"), DesignCharacter(name="刘备")],
        scenes=[DesignScene(name="军帐")],
    )
    sl = await generate_shot_list_draft(screenplay=screenplay, design_list=design_list, llm=llm)
    assert sl.shots[0].action_beats == ["张飞猛地抽剑架颈", "刘备扑上夺剑", "宝剑坠地紧抱"]


async def test_shot_list_draft_parses_target_name_on_dialogue():
    """INC-001 §H:对白行解析出 target_name(对谁说),驱动后续 eyeline。"""
    llm = _llm(
        '{"shots": [{"shot_size": "中景", "visual_prompt": "二人对峙", '
        '"dialogue_lines": [{"character_name": "智伯", "text": "把地给我。", '
        '"target_name": "韩康子"}], '
        '"character_names": ["智伯", "韩康子"], "duration_s": 5}]}'
    )
    screenplay = Screenplay(
        scenes=[
            ScreenplayScene(
                scene_no=1,
                location="宫殿",
                characters_present=["智伯", "韩康子"],
                dialogue=[ScreenplayDialogueLine(character_name="智伯", text="把地给我。")],
            )
        ]
    )
    design_list = DesignList(
        characters=[DesignCharacter(name="智伯"), DesignCharacter(name="韩康子")],
        scenes=[DesignScene(name="宫殿")],
    )
    sl = await generate_shot_list_draft(screenplay=screenplay, design_list=design_list, llm=llm)
    assert sl.shots[0].dialogue_lines[0].target_name == "韩康子"


# ── INC-004 §1.2 shot_type/ots_foreground 解析 ──────────────────────────────


async def test_shot_list_draft_parses_shot_type_and_ots_foreground():
    llm = _llm(
        '{"shots": [{"shot_size": "中景", "shot_type": "ots", "ots_foreground": "智伯", '
        '"visual_prompt": "过肩镜", "dialogue_lines": [], '
        '"character_names": ["智伯", "韩康子"], "duration_s": 5}]}'
    )
    screenplay = Screenplay(
        scenes=[ScreenplayScene(scene_no=1, location="宫殿", characters_present=["智伯", "韩康子"])]
    )
    design_list = DesignList(
        characters=[DesignCharacter(name="智伯"), DesignCharacter(name="韩康子")],
        scenes=[DesignScene(name="宫殿")],
    )
    sl = await generate_shot_list_draft(screenplay=screenplay, design_list=design_list, llm=llm)
    assert sl.shots[0].shot_type == "ots"
    assert sl.shots[0].ots_foreground == "智伯"


async def test_shot_list_draft_unrecognized_shot_type_dropped():
    """LLM 吐出词表外的 shot_type(如凭空编的类型)→ 丢弃成"未分类",不硬塞可能误导 lint 的值。"""
    llm = _llm(
        '{"shots": [{"shot_size": "中景", "shot_type": "extreme_wide_pan", '
        '"visual_prompt": "v", "dialogue_lines": [], '
        '"character_names": ["智伯"], "duration_s": 5}]}'
    )
    screenplay = Screenplay(scenes=[ScreenplayScene(scene_no=1, location="宫殿")])
    design_list = DesignList(
        characters=[DesignCharacter(name="智伯")], scenes=[DesignScene(name="宫殿")]
    )
    sl = await generate_shot_list_draft(screenplay=screenplay, design_list=design_list, llm=llm)
    assert sl.shots[0].shot_type == ""


async def test_shot_list_draft_ots_foreground_dropped_when_not_ots():
    """shot_type 不是 ots 时,即便 LLM 填了 ots_foreground 也丢弃(不是这个类型的字段)。"""
    llm = _llm(
        '{"shots": [{"shot_size": "中景", "shot_type": "clean_single", '
        '"ots_foreground": "智伯", "visual_prompt": "v", "dialogue_lines": [], '
        '"character_names": ["智伯"], "duration_s": 5}]}'
    )
    screenplay = Screenplay(scenes=[ScreenplayScene(scene_no=1, location="宫殿")])
    design_list = DesignList(
        characters=[DesignCharacter(name="智伯")], scenes=[DesignScene(name="宫殿")]
    )
    sl = await generate_shot_list_draft(screenplay=screenplay, design_list=design_list, llm=llm)
    assert sl.shots[0].shot_type == "clean_single"
    assert sl.shots[0].ots_foreground == ""


async def test_shot_list_draft_ots_foreground_unlocked_name_dropped():
    """ots_foreground 填了一个没锁定过的人名(LLM 编的)→ 丢弃,不发明新角色。"""
    llm = _llm(
        '{"shots": [{"shot_size": "中景", "shot_type": "ots", "ots_foreground": "路人甲", '
        '"visual_prompt": "v", "dialogue_lines": [], '
        '"character_names": ["智伯", "韩康子"], "duration_s": 5}]}'
    )
    screenplay = Screenplay(
        scenes=[ScreenplayScene(scene_no=1, location="宫殿", characters_present=["智伯", "韩康子"])]
    )
    design_list = DesignList(
        characters=[DesignCharacter(name="智伯"), DesignCharacter(name="韩康子")],
        scenes=[DesignScene(name="宫殿")],
    )
    sl = await generate_shot_list_draft(screenplay=screenplay, design_list=design_list, llm=llm)
    assert sl.shots[0].shot_type == "ots"
    assert sl.shots[0].ots_foreground == ""


# ── INC-004 §4.1/§4.4 quality_tier(纯规则,不上 LLM)──────────────────────────


def test_classify_quality_tier_pose_difference_keyword_flags_key():
    """≥2 人同框且 blocking 出现"伏地"这类姿态落差词 → key(①,真机验证过)。"""
    blocking = [
        ShotBlocking(character_name="王生", position="石阶中央，伏地", facing="面朝石阶上方"),
        ShotBlocking(character_name="老道士", position="石阶下两级", facing="仰视王生后颈"),
    ]
    tier = classify_quality_tier(
        character_names=["王生", "老道士"], blocking=blocking, shot_type="master"
    )
    assert tier == "key"


def test_classify_quality_tier_pose_keyword_in_facing_also_flags_key():
    """关键词出现在 facing 里(不只 position)也要命中——"俯视"经常写在朝向描述上。"""
    blocking = [ShotBlocking(character_name="老道士", position="阶顶", facing="居高俯视王生")]
    tier = classify_quality_tier(
        character_names=["王生", "老道士"], blocking=blocking, shot_type="clean_single"
    )
    assert tier == "key"


def test_classify_quality_tier_single_character_pose_keyword_not_flagged():
    """单人镜就算 blocking 写了姿态词,也不算"构图级姿态差异"(至少要 2 人)→ standard。"""
    blocking = [ShotBlocking(character_name="王生", position="伏地", facing="")]
    tier = classify_quality_tier(
        character_names=["王生"], blocking=blocking, shot_type="clean_single"
    )
    assert tier == "standard"


def test_classify_quality_tier_two_shot_flags_key_without_pose_keyword():
    """②双人复杂关系镜(soffy 定的外推范围,2026-07-19):≥2 人 + shot_type=two_shot,
    即便 blocking 没有姿态落差词也标 key。"""
    blocking = [
        ShotBlocking(character_name="王生", position="画面左侧", facing="面向老道士"),
        ShotBlocking(character_name="老道士", position="画面右侧", facing="面向王生"),
    ]
    tier = classify_quality_tier(
        character_names=["王生", "老道士"], blocking=blocking, shot_type="two_shot"
    )
    assert tier == "key"


def test_classify_quality_tier_ots_flags_key_without_pose_keyword():
    """同上,ots 也算双人复杂关系镜 → key。"""
    tier = classify_quality_tier(character_names=["王生", "老道士"], blocking=[], shot_type="ots")
    assert tier == "key"


def test_classify_quality_tier_master_not_flagged_without_pose_keyword():
    """master(建场全景,人物占比小)不算"双人复杂关系镜"——没有姿态落差词时不标 key
    (soffy 定:排除 master,规则宁窄勿宽)。"""
    tier = classify_quality_tier(
        character_names=["王生", "老道士"], blocking=[], shot_type="master"
    )
    assert tier == "standard"


def test_classify_quality_tier_clean_single_no_longer_flags_key():
    """情绪峰值 clean_single 这条已被 soffy 移除(2026-07-19:本地单人镜质量本来就稳,
    没有证据支撑要花钱)——即便曾经的强情绪词也不再触发,clean_single 恒 standard
    (除非同时满足①,但 clean_single 结构上不可能 ≥2 人)。"""
    tier = classify_quality_tier(character_names=["王生"], blocking=[], shot_type="clean_single")
    assert tier == "standard"


def test_classify_quality_tier_defaults_to_standard_with_no_signals():
    tier = classify_quality_tier(character_names=[], blocking=[], shot_type="insert")
    assert tier == "standard"


async def test_shot_list_draft_sets_quality_tier_key_for_pose_difference():
    """端到端:generate_shot_list_draft 产出的 shot 真的带上了 quality_tier(不是只有纯函数
    测试过,LLM 输出解析这条链路也要接上)。"""
    llm = _llm(
        '{"shots": [{"shot_size": "全景", "shot_type": "master", '
        '"visual_prompt": "二人同框", "dialogue_lines": [], '
        '"blocking": [{"character_name": "王生", "position": "石阶中央，伏地", "facing": ""}, '
        '{"character_name": "老道士", "position": "阶下", "facing": "仰视"}], '
        '"character_names": ["王生", "老道士"], "duration_s": 6}]}'
    )
    screenplay = Screenplay(
        scenes=[ScreenplayScene(scene_no=1, location="山门", characters_present=["王生", "老道士"])]
    )
    design_list = DesignList(
        characters=[DesignCharacter(name="王生"), DesignCharacter(name="老道士")],
        scenes=[DesignScene(name="山门")],
    )
    sl = await generate_shot_list_draft(screenplay=screenplay, design_list=design_list, llm=llm)
    assert sl.shots[0].quality_tier == "key"


# ── INC-001 §K.1 质量闸(参考图映射污染 → 修正重试)────────────────────────────


def test_contaminated_detects_reference_mapping_markers():
    from hevi.director.shot_list import _contaminated

    assert _contaminated({"shots": [{"visual_prompt": "图1里的人递给图2"}]})
    assert _contaminated({"shots": [{"visual_prompt": "正常", "action_beats": ["参考图中的动作"]}]})
    assert not _contaminated({"shots": [{"visual_prompt": "智伯把地图递给韩康子"}]})
    assert not _contaminated({})


async def test_shot_list_qc_retries_on_reference_contamination():
    """§K.1:LLM 首次输出混入「图1/图2」→ 带修正重试一次,落库用干净的重试结果。"""
    contaminated = (
        '{"shots": [{"visual_prompt": "图1中的智伯把地图递给图2的韩康子", '
        '"dialogue_lines": [], "character_names": ["智伯"], "duration_s": 5}]}'
    )
    clean = (
        '{"shots": [{"visual_prompt": "智伯把地图递给韩康子", '
        '"dialogue_lines": [], "character_names": ["智伯"], "duration_s": 5}]}'
    )

    calls = {"n": 0}

    def _llm_alt(*, messages, **kw):
        content = contaminated if calls["n"] == 0 else clean
        calls["n"] += 1
        return {"content": content}

    screenplay = Screenplay(
        scenes=[
            ScreenplayScene(
                scene_no=1, location="宫殿", characters_present=["智伯", "韩康子"], narration="x"
            )
        ]
    )
    design_list = DesignList(
        characters=[DesignCharacter(name="智伯"), DesignCharacter(name="韩康子")],
        scenes=[DesignScene(name="宫殿")],
    )
    sl = await generate_shot_list_draft(
        screenplay=screenplay, design_list=design_list, llm=_llm_alt
    )
    assert calls["n"] == 2  # 重试了一次
    assert "图1" not in sl.shots[0].visual_prompt
    assert sl.shots[0].visual_prompt == "智伯把地图递给韩康子"
