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
)
from hevi.director.screenplay import generate_screenplay_draft
from hevi.director.shot_list import generate_shot_list_draft


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
