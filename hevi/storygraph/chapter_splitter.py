"""章节切分器 - 将长文切分为章节块,便于分批抽取 StoryGraph。

支持多种切分策略:
1. 显式章节标记 (第X章, Chapter X, 卷X)
2. 空行分段 (连续 2+ 空行)
3. 固定长度切分 (兜底,避免单章过长)

对标 Toonflow 的章节事件图谱提取能力,补全 Hevi 长篇导入的短板。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class Chapter:
    """章节块。"""

    chapter_id: str  # 确定性 ID,如 "ch_001"
    title: str  # 章节标题 (无则用前 20 字)
    content: str  # 章节正文
    char_count: int  # 字符数
    source_span: tuple[int, int]  # 在原文中的 [start, end) 位置

    def to_dict(self) -> dict[str, Any]:
        return {
            "chapter_id": self.chapter_id,
            "title": self.title,
            "content": self.content,
            "char_count": self.char_count,
            "source_span": self.source_span,
        }


# 常见章节标记正则
CHAPTER_PATTERNS = [
    # 中文: 第一章, 第1章, 第一回, 卷一
    r"^[ \s]*(第[零一二三四五六七八九十百千万\d]+[章回节卷集篇部])[ \s]*(.+)?$",
    # 英文: Chapter 1, CHAPTER I, Part 1
    r"^[ \s]*((?:Chapter|CHAPTER|Part|PART|Book|BOOK)[ \s]*[\dIVXLCDM]+)[ \s]*(.+)?$",
    # 数字序号: 1., 1), (1), 【1】
    r"^[ \s]*[\(【]?(\d+)[\)】]?[.、: \s]*(.+)?$",
]

# 最大单章长度 (避免 LLM 上下文超限)
MAX_CHAPTER_LENGTH = 8000


def _detect_chapter_boundaries(text: str) -> list[tuple[int, str]]:
    """检测章节边界,返回 [(position, title), ...]。

    优先级:
    1. 显式章节标记 (第X章, Chapter X)
    2. 连续 3+ 空行 (兜底)
    """
    boundaries: list[tuple[int, str]] = []
    lines = text.split("\n")
    current_pos = 0

    # 尝试显式章节标记
    for i, line in enumerate(lines):
        for pattern in CHAPTER_PATTERNS:
            match = re.match(pattern, line.strip())
            if match:
                title = match.group(0).strip()
                boundaries.append((current_pos, title))
                break
        current_pos += len(line) + 1  # +1 for \n

    # 如果没有检测到显式章节,尝试用空行分段
    if not boundaries:
        current_pos = 0
        empty_line_count = 0
        for i, line in enumerate(lines):
            if not line.strip():
                empty_line_count += 1
                if empty_line_count >= 3:  # 连续 3 空行视为章节边界
                    # 取下一非空行前 20 字作为标题
                    title = ""
                    for j in range(i + 1, min(i + 5, len(lines))):
                        if lines[j].strip():
                            title = lines[j].strip()[:20]
                            break
                    boundaries.append((current_pos, title or f"段落 {len(boundaries) + 1}"))
                    empty_line_count = 0
            else:
                empty_line_count = 0
            current_pos += len(line) + 1

    return boundaries


def _split_into_chunks(
    text: str, boundaries: list[tuple[int, str]]
) -> list[tuple[str, str, tuple[int, int]]]:
    """按边界切分文本,返回 [(title, content, span), ...]。

    如果单章超过 MAX_CHAPTER_LENGTH,递归切分。
    """
    if not boundaries:
        # 无边界 → 整文作为一章
        title = text.strip()[:20] or "全文"
        return [(title, text, (0, len(text)))]

    chunks: list[tuple[str, str, tuple[int, int]]] = []

    # 如果第一个边界不在文本开头,添加一个隐式边界
    if boundaries[0][0] > 0:
        boundaries = [(0, "")] + boundaries

    for i, (start_pos, title) in enumerate(boundaries):
        end_pos = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(text)
        content = text[start_pos:end_pos].strip()

        if not content:
            continue

        # 超长章节递归切分
        if len(content) > MAX_CHAPTER_LENGTH:
            # 尝试用空行切分
            sub_boundaries = _detect_chapter_boundaries(content)
            if sub_boundaries and len(sub_boundaries) > 1:
                sub_chunks = _split_into_chunks(content, sub_boundaries)
                for j, (sub_title, sub_content, sub_span) in enumerate(sub_chunks):
                    # 调整 span 到全文坐标系
                    abs_start = start_pos + sub_span[0]
                    abs_end = start_pos + sub_span[1]
                    full_title = f"{title} - {sub_title}" if sub_title else title
                    chunks.append((full_title, sub_content, (abs_start, abs_end)))
            else:
                # 无子边界,强制按长度切分
                for j in range(0, len(content), MAX_CHAPTER_LENGTH):
                    sub_content = content[j : j + MAX_CHAPTER_LENGTH]
                    abs_start = start_pos + j
                    abs_end = start_pos + j + len(sub_content)
                    part_num = j // MAX_CHAPTER_LENGTH + 1
                    sub_title = f"{title} (部分 {part_num})" if title else f"部分 {part_num}"
                    chunks.append((sub_title, sub_content, (abs_start, abs_end)))
        else:
            chunks.append((title, content, (start_pos, end_pos)))

    return chunks


def split_text_to_chapters(text: str, source_name: str = "") -> list[Chapter]:
    """将长文切分为章节列表。

    Args:
        text: 原文
        source_name: 来源名称 (用于生成 chapter_id 前缀)

    Returns:
        Chapter 列表,按原文顺序
    """
    if not text or not text.strip():
        return []

    # 检测章节边界
    boundaries = _detect_chapter_boundaries(text)

    # 切分为块
    chunks = _split_into_chunks(text, boundaries)

    # 构建 Chapter 对象
    prefix = source_name[:3].upper() if source_name else "CH"
    chapters: list[Chapter] = []

    for i, (title, content, span) in enumerate(chunks, start=1):
        chapter_id = f"{prefix}_{i:03d}"
        # 如果没有标题,用内容前 20 字
        if not title:
            title = content.strip()[:20] or f"章节 {i}"

        chapters.append(
            Chapter(
                chapter_id=chapter_id,
                title=title,
                content=content,
                char_count=len(content),
                source_span=span,
            )
        )

    return chapters


def merge_chapters_to_story_graph(
    chapters: list[Chapter],
    chapter_graphs: list[Any],  # list[StoryGraph]
    source_name: str = "",
) -> Any:
    """合并多章的 StoryGraph 为单一 StoryGraph。

    处理:
    1. 合并 characters (按 name 去重,char_id 重新编号)
    2. 合并 events (按 source_span 排序,event_id 重新编号)
    3. 合并 quotes (按 event_id 关联)
    4. 合并 locations (按 name 去重)

    Args:
        chapters: 原始章节列表
        chapter_graphs: 每章对应的 StoryGraph
        source_name: 来源名称

    Returns:
        合并后的 StoryGraph
    """
    from hevi.storygraph.schemas import (
        StoryCharacter,
        StoryEvent,
        StoryGraph,
        StoryLocation,
        StoryMeta,
        StoryQuote,
        StoryRelationship,
    )

    # 合并 characters (按 name 去重)
    char_name_to_id: dict[str, str] = {}
    all_characters: list[StoryCharacter] = []
    char_id_remap: dict[str, str] = {}  # 旧 char_id → 新 char_id

    char_counter = 1
    for graph in chapter_graphs:
        for char in graph.characters:
            if char.name not in char_name_to_id:
                new_id = f"C{char_counter:03d}"
                char_name_to_id[char.name] = new_id
                char_id_remap[char.char_id] = new_id
                new_char = char.model_copy(update={"char_id": new_id})
                all_characters.append(new_char)
                char_counter += 1
            else:
                char_id_remap[char.char_id] = char_name_to_id[char.name]

    # 合并 events (按 source_span 排序)
    all_events: list[StoryEvent] = []
    event_id_remap: dict[str, str] = {}

    # 收集所有 events 并排序
    events_with_span: list[tuple[StoryEvent, tuple[int, int]]] = []
    for graph in chapter_graphs:
        for event in graph.events:
            events_with_span.append((event, event.source_span))

    events_with_span.sort(key=lambda x: x[1][0])  # 按 start position 排序

    event_counter = 1
    for event, _ in events_with_span:
        new_id = f"E{event_counter:03d}"
        event_id_remap[event.event_id] = new_id
        # 重新映射 actors
        new_actors = [char_id_remap.get(a, a) for a in event.actors]
        # 重新映射 causes/effects
        new_causes = [event_id_remap.get(c, c) for c in event.causes if c in event_id_remap]
        new_effects = [event_id_remap.get(e, e) for e in event.effects if e in event_id_remap]
        new_event = event.model_copy(
            update={
                "event_id": new_id,
                "actors": new_actors,
                "causes": new_causes,
                "effects": new_effects,
            }
        )
        all_events.append(new_event)
        event_counter += 1

    # 合并 quotes
    all_quotes: list[StoryQuote] = []
    quote_counter = 1
    for graph in chapter_graphs:
        for quote in graph.quotes:
            new_id = f"Q{quote_counter:03d}"
            new_speaker = char_id_remap.get(quote.speaker, quote.speaker)
            new_event_id = event_id_remap.get(quote.event_id) if quote.event_id else None
            new_quote = quote.model_copy(
                update={
                    "quote_id": new_id,
                    "speaker": new_speaker,
                    "event_id": new_event_id,
                }
            )
            all_quotes.append(new_quote)
            quote_counter += 1

    # 合并 locations (按 name 去重)
    loc_name_to_id: dict[str, str] = {}
    all_locations: list[StoryLocation] = []

    loc_counter = 1
    for graph in chapter_graphs:
        for loc in graph.locations:
            if loc.name not in loc_name_to_id:
                new_id = f"L{loc_counter:03d}"
                loc_name_to_id[loc.name] = new_id
                new_loc = loc.model_copy(update={"location_id": new_id})
                all_locations.append(new_loc)
                loc_counter += 1

    # 构建合并后的 StoryGraph
    meta = StoryMeta(
        source=source_name,
        char_count=sum(ch.char_count for ch in chapters),
        chapter_refs=[ch.chapter_id for ch in chapters],
    )

    return StoryGraph(
        meta=meta,
        characters=all_characters,
        relationships=[],  # 阶段 1 不填充
        events=all_events,
        quotes=all_quotes,
        locations=all_locations,
        arcs=[],  # 阶段 1 不填充
    )
