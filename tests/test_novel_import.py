"""novel_import 能力测试：夹具全部现编短文本，不引用真实剧情与人物。"""

from __future__ import annotations

import json
import re

import pytest

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.novel_import import map_to_episodes, parse_chapters


def _paragraphs(text: str) -> list[str]:
    return [para for para in re.split(r"\n\s*\n", text.strip()) if para.strip()]


def _chapter(no: int, title: str, text: str) -> dict:
    return {"chapter_no": no, "title": title, "text": text}


_CH1 = (
    "晨光照进小院，石桌上还留着昨夜的雨水。\n\n"
    "阿梨推开木门，看见信箱里塞着一封没有署名的信。\n\n"
    "她把信拆开，读了两遍，又折好放回信封。\n\n"
    "院外的集市已经开了，叫卖声顺着巷子传进来。"
)
_CH2 = (
    "傍晚，阿梨沿着河边往回走。\n\n"
    "桥上站着一个卖灯的人，灯火一盏一盏亮起来。\n\n"
    "她停下来，数了数灯，又继续往前走。\n\n"
    "回到小院时，月亮已经升到屋顶上了。"
)


def test_two_chapters_four_episodes():
    episodes = map_to_episodes(
        [_chapter(1, "晨信", _CH1), _chapter(2, "河灯", _CH2)],
        episodes_per_chapter=2,
    )
    assert len(episodes) == 4
    assert [ep["episode_no"] for ep in episodes] == [1, 2, 3, 4]
    assert [ep["chapter_no"] for ep in episodes] == [1, 1, 2, 2]
    assert [ep["part"] for ep in episodes] == [1, 2, 1, 2]
    assert episodes[0]["title"] == "晨信（第1部分）"
    assert episodes[1]["title"] == "晨信（第2部分）"
    assert episodes[2]["title"] == "河灯（第1部分）"
    assert episodes[3]["title"] == "河灯（第2部分）"
    assert all(ep["source_chapter_title"] in ("晨信", "河灯") for ep in episodes)
    assert all(ep["text_slice"] for ep in episodes)
    assert all(ep["synopsis"] for ep in episodes)
    assert all(ep["char_count"] == len(ep["text_slice"]) for ep in episodes)
    json.dumps(episodes)  # 输出必须 JSON 可序列化


def test_missing_chapter_number_raises_and_names_missing():
    with pytest.raises(CapabilityError, match="2"):
        parse_chapters([_chapter(1, "甲", "第一段。\n\n第二段。"), _chapter(3, "丙", "第三段。")])
    with pytest.raises(CapabilityError, match="2"):
        map_to_episodes([_chapter(1, "甲", "第一段。\n\n第二段。"), _chapter(3, "丙", "第三段。")])


def test_duplicate_chapter_number_raises():
    with pytest.raises(CapabilityError, match="重复"):
        parse_chapters([_chapter(1, "甲", "第一段。"), _chapter(1, "甲又", "第二段。")])


def test_not_starting_from_one_raises():
    with pytest.raises(CapabilityError, match="1"):
        parse_chapters([_chapter(2, "乙", "第一段。"), _chapter(3, "丙", "第二段。")])


def test_empty_title_raises():
    with pytest.raises(CapabilityError):
        parse_chapters([_chapter(1, "", "第一段。")])
    with pytest.raises(CapabilityError):
        parse_chapters([_chapter(1, "   ", "第一段。")])


def test_empty_text_raises():
    with pytest.raises(CapabilityError):
        parse_chapters([_chapter(1, "甲", "")])
    with pytest.raises(CapabilityError):
        parse_chapters([_chapter(1, "甲", "   \n\n  ")])


def test_empty_chapter_list_raises():
    with pytest.raises(CapabilityError):
        parse_chapters([])


def test_dialogue_char_count():
    text = (
        "阿梨问：“早上好，今天去集市吗？”\n\n"
        "对方答：“一起走吧。”\n\n"
        "两人并肩出了门。\n\n"
        "巷子里飘着炊烟的味道。"
    )
    episodes = map_to_episodes([_chapter(1, "问路", text)], episodes_per_chapter=2)
    assert len(episodes) == 2
    # “早上好，今天去集市吗？”内 11 字（含标点）；“一起走吧。”内 5 字。
    assert sum(ep["dialogue_char_count"] for ep in episodes) == 16
    assert all(ep["dialogue_char_count"] >= 0 for ep in episodes)


def test_text_slices_preserve_paragraph_sequence():
    chapters = [_chapter(1, "晨信", _CH1), _chapter(2, "河灯", _CH2)]
    episodes = map_to_episodes(chapters, episodes_per_chapter=2)
    for chapter, group in zip(chapters, [episodes[0:2], episodes[2:4]]):
        rebuilt = []
        for ep in group:
            rebuilt.extend(_paragraphs(ep["text_slice"]))
        assert rebuilt == _paragraphs(chapter["text"])


def test_single_chapter_single_episode():
    episodes = map_to_episodes(
        [_chapter(1, "独章", "只有一段正文，没有第二段。")], episodes_per_chapter=1
    )
    assert len(episodes) == 1
    assert episodes[0]["episode_no"] == 1
    assert episodes[0]["part"] == 1
    assert episodes[0]["title"] == "独章（第1部分）"
    assert episodes[0]["text_slice"] == "只有一段正文，没有第二段。"
    assert episodes[0]["synopsis"] == "只有一段正文，没有第二段。"


def test_too_few_paragraphs_raises_and_names_chapter():
    with pytest.raises(CapabilityError, match="1"):
        map_to_episodes(
            [_chapter(1, "短章", "只有一段。")], episodes_per_chapter=2
        )


def test_episodes_per_chapter_below_one_raises():
    with pytest.raises(CapabilityError):
        map_to_episodes([_chapter(1, "甲", "第一段。\n\n第二段。")], episodes_per_chapter=0)
    with pytest.raises(CapabilityError):
        map_to_episodes([_chapter(1, "甲", "第一段。\n\n第二段。")], episodes_per_chapter=-1)


def test_synopsis_truncation_marker():
    long_para = "雨" * 210
    episodes = map_to_episodes(
        [_chapter(1, "长段", long_para)], episodes_per_chapter=1
    )
    assert episodes[0]["synopsis"] == "雨" * 200 + "……"
    short = map_to_episodes(
        [_chapter(1, "短段", "短短一段。")], episodes_per_chapter=1
    )
    assert short[0]["synopsis"] == "短短一段。"
    assert "……" not in short[0]["synopsis"]
