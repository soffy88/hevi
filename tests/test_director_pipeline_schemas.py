"""SPEC-003 主线导演流水线契约测试(Concept/Screenplay/DesignList/ShotList)。"""

from __future__ import annotations

from hevi.director.pipeline_schemas import (
    Concept,
    DesignCharacter,
    DesignList,
    DesignProp,
    DesignScene,
    Screenplay,
    ScreenplayDialogueLine,
    ScreenplayScene,
    ShotBlocking,
    ShotList,
    ShotListDialogueLine,
    ShotListItem,
)


class TestConcept:
    def test_defaults(self):
        c = Concept()
        assert c.theme == ""
        assert c.duration_archetype == "1-5min"


class TestScreenplay:
    def test_dialogue_line_requires_character_and_text(self):
        line = ScreenplayDialogueLine(character_name="老者", text="城破在即。")
        assert line.character_name == "老者"

    def test_scene_defaults(self):
        s = ScreenplayScene(scene_no=1)
        assert s.dialogue == []
        assert s.characters_present == []

    def test_screenplay_holds_scenes(self):
        sp = Screenplay(
            scenes=[
                ScreenplayScene(
                    scene_no=1,
                    location="宫殿",
                    dialogue=[ScreenplayDialogueLine(character_name="王", text="退下。")],
                )
            ]
        )
        assert len(sp.scenes) == 1
        assert sp.scenes[0].dialogue[0].text == "退下。"


class TestDesignList:
    def test_character_starts_unlocked(self):
        c = DesignCharacter(name="智伯")
        assert c.subject_id is None
        assert c.is_lead is False

    def test_scene_and_prop_defaults(self):
        s = DesignScene(name="宫殿")
        p = DesignProp(name="玉玦")
        assert s.subject_id is None
        assert p.subject_id is None

    def test_design_list_three_lists(self):
        dl = DesignList(
            characters=[DesignCharacter(name="智伯")],
            scenes=[DesignScene(name="宫殿")],
            props=[DesignProp(name="玉玦")],
        )
        assert len(dl.characters) == 1
        assert len(dl.scenes) == 1
        assert len(dl.props) == 1


class TestShotList:
    def test_dialogue_line_empty_character_name_is_narration(self):
        line = ShotListDialogueLine(text="很久以前……")
        assert line.character_name == ""  # 空 = 旁白

    def test_dialogue_line_with_speaker_is_dialogue(self):
        line = ShotListDialogueLine(character_name="智伯", text="要地予我。")
        assert line.character_name == "智伯"

    def test_blocking_defaults(self):
        b = ShotBlocking(character_name="智伯")
        assert b.position == ""

    def test_shot_item_defaults(self):
        item = ShotListItem(shot_id="SH001", scene_no=1)
        assert item.dialogue_lines == []
        assert item.duration_s == 5.0
        assert item.shot_type == ""  # 未分类,向后兼容旧 work(INC-004 §1.1)
        assert item.ots_foreground == ""
        assert item.quality_tier == "standard"  # 默认 standard,不误标 key(INC-004 §4.1)

    def test_shot_item_shot_type_and_ots_foreground(self):
        item = ShotListItem(shot_id="SH001", scene_no=1, shot_type="ots", ots_foreground="王生")
        assert item.shot_type == "ots"
        assert item.ots_foreground == "王生"

    def test_shot_list_multi_character_dialogue(self):
        """治"只有旁白没对白":一个镜头里两个角色各自的台词行都能表达。"""
        item = ShotListItem(
            shot_id="SH001",
            scene_no=1,
            dialogue_lines=[
                ShotListDialogueLine(character_name="智伯", text="要地予我。"),
                ShotListDialogueLine(character_name="赵襄子", text="不给。"),
            ],
            character_names=["智伯", "赵襄子"],
        )
        sl = ShotList(shots=[item])
        assert [d.character_name for d in sl.shots[0].dialogue_lines] == ["智伯", "赵襄子"]
