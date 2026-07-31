"""章节切分器测试。

测试覆盖:
- 显式章节标记检测 (第X章, Chapter X)
- 空行分段检测
- 超长章节递归切分
- 合并 StoryGraph
"""

from __future__ import annotations

import pytest

from hevi.storygraph.chapter_splitter import (
    Chapter,
    split_text_to_chapters,
    merge_chapters_to_story_graph,
)
from hevi.storygraph.schemas import (
    StoryCharacter,
    StoryEvent,
    StoryGraph,
    StoryMeta,
)


class TestChapterSplitter:
    """章节切分器测试。"""

    def test_split_by_explicit_chinese_chapters(self) -> None:
        """测试中文显式章节标记切分。"""
        text = """第一章 开端

这是第一章的内容。主角登场了。

第二章 发展

故事继续发展，发生了很多事。

第三章 高潮

最终的高潮来临了。"""

        chapters = split_text_to_chapters(text, source_name="测试小说")

        assert len(chapters) == 3
        assert "第一章" in chapters[0].title
        assert "第二章" in chapters[1].title
        assert "第三章" in chapters[2].title

    def test_split_by_explicit_english_chapters(self) -> None:
        """测试英文显式章节标记切分。"""
        text = """Chapter 1 Introduction

This is the first chapter.

Chapter 2 Development

The story continues.

Chapter 3 Conclusion

The end."""

        chapters = split_text_to_chapters(text, source_name="TestNovel")

        assert len(chapters) == 3
        assert "Chapter 1" in chapters[0].title
        assert "Chapter 2" in chapters[1].title
        assert "Chapter 3" in chapters[2].title

    def test_split_by_empty_lines(self) -> None:
        """测试空行分段切分。"""
        text = """这是第一部分的内容。

这里是第二段，与第一段之间有三个空行。



这是第三段的内容。"""

        chapters = split_text_to_chapters(text, source_name="空行测试")

        # 应该被切分为至少 2 段
        assert len(chapters) >= 2

    def test_split_long_chapter(self) -> None:
        """测试超长章节递归切分。"""
        # 生成超长文本 (> 8000 字符)
        long_text = "第一章 超长章节\n\n" + "这是一段很长的内容。" * 900

        chapters = split_text_to_chapters(long_text, source_name="超长测试")

        # 应该被切分为多个子章节
        assert len(chapters) >= 2
        # 每个子章节应该不超过 8000 字符
        for ch in chapters:
            assert ch.char_count <= 8000

    def test_empty_text(self) -> None:
        """测试空文本返回空列表。"""
        chapters = split_text_to_chapters("", source_name="空")
        assert chapters == []

    def test_single_chapter(self) -> None:
        """测试无章节标记的单段文本。"""
        text = "这是一段简短的文本，没有章节标记。"

        chapters = split_text_to_chapters(text, source_name="单章")

        assert len(chapters) == 1
        assert chapters[0].content == text

    def test_chapter_id_format(self) -> None:
        """测试章节 ID 格式。"""
        text = """第一章 A

内容 A

第二章 B

内容 B"""

        chapters = split_text_to_chapters(text, source_name="测试")

        # ID 应该使用 source_name 前缀
        for ch in chapters:
            assert ch.chapter_id.startswith("测试_")
            # 应该是 CH_001, CH_002 格式
            assert len(ch.chapter_id) == len("测试_001")

    def test_chapter_span_accuracy(self) -> None:
        """测试章节 source_span 准确性。"""
        text = """第一章 开始

这是第一章的内容。

第二章 继续

这是第二章的内容。"""

        chapters = split_text_to_chapters(text, source_name="测试")

        # 每个章节的 span 应该覆盖其内容
        for ch in chapters:
            start, end = ch.source_span
            assert start >= 0
            assert end > start
            assert end <= len(text)
            # 从 span 提取的文本应该包含章节内容
            extracted = text[start:end]
            assert ch.content[:20] in extracted  # 至少前 20 字符能匹配


class TestChapterMerger:
    """章节 StoryGraph 合并测试。"""

    def test_merge_two_chapters(self) -> None:
        """测试合并两个章节的 StoryGraph。"""
        # 创建两个章节
        ch1 = Chapter(
            chapter_id="CH_001",
            title="第一章",
            content="第一章内容",
            char_count=6,
            source_span=(0, 6),
        )
        ch2 = Chapter(
            chapter_id="CH_002",
            title="第二章",
            content="第二章内容",
            char_count=6,
            source_span=(6, 12),
        )

        # 创建两个 StoryGraph
        graph1 = StoryGraph(
            meta=StoryMeta(source="第一章", char_count=6, chapter_refs=["CH_001"]),
            characters=[
                StoryCharacter(
                    char_id="C001",
                    name="张三",
                    aliases=["小张"],
                    source_spans=[(0, 2)],
                )
            ],
            events=[
                StoryEvent(
                    event_id="E001",
                    summary="事件1",
                    actors=["C001"],
                    source_span=(0, 6),
                )
            ],
        )

        graph2 = StoryGraph(
            meta=StoryMeta(source="第二章", char_count=6, chapter_refs=["CH_002"]),
            characters=[
                StoryCharacter(
                    char_id="C001",
                    name="张三",  # 同一个人
                    aliases=["小张"],
                    source_spans=[(6, 8)],
                ),
                StoryCharacter(
                    char_id="C002",
                    name="李四",
                    source_spans=[(8, 10)],
                ),
            ],
            events=[
                StoryEvent(
                    event_id="E001",
                    summary="事件2",
                    actors=["C001", "C002"],
                    source_span=(6, 12),
                )
            ],
        )

        # 合并
        merged = merge_chapters_to_story_graph(
            chapters=[ch1, ch2],
            chapter_graphs=[graph1, graph2],
            source_name="测试小说",
        )

        # 验证合并结果
        assert merged.meta.source == "测试小说"
        assert len(merged.meta.chapter_refs) == 2  # 两个章节

        # characters 应该去重 (张三只出现一次)
        assert len(merged.characters) == 2  # 张三 + 李四

        # events 应该按 source_span 排序
        assert len(merged.events) == 2
        assert merged.events[0].source_span[0] < merged.events[1].source_span[0]

        # event_id 应该重新编号
        assert merged.events[0].event_id == "E001"
        assert merged.events[1].event_id == "E002"

    def test_merge_empty_graphs(self) -> None:
        """测试合并空 StoryGraph。"""
        ch1 = Chapter(
            chapter_id="CH_001",
            title="空章节",
            content="",
            char_count=0,
            source_span=(0, 0),
        )

        graph1 = StoryGraph(
            meta=StoryMeta(source="空", char_count=0, chapter_refs=["CH_001"]),
            characters=[],
            events=[],
        )

        merged = merge_chapters_to_story_graph(
            chapters=[ch1],
            chapter_graphs=[graph1],
            source_name="空测试",
        )

        assert len(merged.characters) == 0
        assert len(merged.events) == 0
