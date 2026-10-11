"""DRAMAPLAN 章节事件图测试（不调网络，用录制的 LLM 响应）。

覆盖：章节切分、逐章事件抽取解析、跨章人物/事件合并（稳定 ID + 跨章因果）、
按集数×时长的改编大纲挑选/压缩、无 LLM 确定性兜底、outline_to_story 裁剪。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from hevi.storygraph.chapters import (
    build_adaptation_outline,
    build_book_event_graph,
    merge_chapter_graphs,
    outline_to_story,
    split_novel_chapters,
)
from hevi.storygraph.schemas import (
    StoryChapter,
    StoryCharacter,
    StoryEvent,
    StoryGraph,
    StoryMeta,
)

NOVEL = """第一章 归乡
张三推开老宅的门，院里落满枯叶。他想起三年前离家时父亲的话。
李四从屋里走出来，低声说：「你终于回来了。」

第二章 旧账
张三找到账本，发现家产早被抵押。王五承认是他经手的。
张三握紧拳头，没有说话。

第三章 对峙
张三当众质问王五，王五拿出字据。李四站出来作证。
张三最终夺回家产，天已破晓。
"""


def _chapter_graph(names: list[str], events: list[dict], quotes: list[dict] | None = None) -> StoryGraph:
    chars = [
        StoryCharacter(char_id=f"C{i:03d}", name=n, aliases=[], description=f"{n}的描写")
        for i, n in enumerate(names, 1)
    ]
    evs = []
    name_to_cid = {c.name: c.char_id for c in chars}
    for i, e in enumerate(events, 1):
        evs.append(
            StoryEvent(
                event_id=f"E{i:03d}",
                summary=e["summary"],
                actors=[name_to_cid[n] for n in e.get("actors", []) if n in name_to_cid],
                beat_type=e.get("beat_type", "过场"),
                dramatic_weight=e.get("weight", 3),
                causes=[f"E{j:03d}" for j in e.get("causes", [])],
                effects=[f"E{j:03d}" for j in e.get("effects", [])],
            )
        )
    return StoryGraph(meta=StoryMeta(source="x"), characters=chars, events=evs)


def test_split_novel_chapters():
    chapters = split_novel_chapters(NOVEL)
    assert len(chapters) == 3
    assert chapters[0][0] == "第一章 归乡"
    assert "张三推开老宅的门" in chapters[0][1]
    assert "王五" in chapters[1][1]


def test_merge_chapter_graphs_merges_characters_and_stable_event_ids():
    metas = [
        StoryChapter(chapter_id="CH01", index=1, title="一", event_ids=["E001", "E002"]),
        StoryChapter(chapter_id="CH02", index=2, title="二", event_ids=["E001"]),
    ]
    g1 = _chapter_graph(
        ["张三", "李四"],
        [
            {"summary": "张三归乡", "actors": ["张三"], "beat_type": "铺垫", "weight": 2},
            {"summary": "李四迎接", "actors": ["张三", "李四"], "beat_type": "冲突", "weight": 4},
        ],
    )
    g2 = _chapter_graph(
        ["张三", "王五"],
        [{"summary": "张三发现抵押", "actors": ["张三", "王五"], "beat_type": "转折", "weight": 5}],
    )
    book = merge_chapter_graphs(source_name="测试书", chapter_metas=metas, chapter_graphs=[g1, g2])

    # 事件 ID 稳定：章号 + 章内序号
    assert [e.event_id for e in book.events] == ["CH01E001", "CH01E002", "CH02E001"]
    # 张三跨章合并成同一 char_id（李四/王五各自独立）
    zhangsan = next(c for c in book.characters if c.name == "张三")
    assert sum(1 for c in book.characters if c.name == "张三") == 1
    assert len(book.characters) == 3
    # 章内 causes/effects 重映射到全局 ID
    assert book.events[1].causes == [] and book.events[0].effects == []
    # 跨章因果缝合：第二章首事件无因 → 补上一章末事件
    assert book.events[2].causes == ["CH01E002"]
    assert "CH02E001" in book.events[1].effects
    # 事件带章引用
    assert book.events[0].chapter_ref == "CH01"
    assert book.events[2].chapter_ref == "CH02"
    # 张三在三个事件里都用同一全局 ID
    zid = zhangsan.char_id
    assert all(zid in e.actors for e in book.events)
    assert book.chapters and book.chapters[0].chapter_id == "CH01"


@pytest.mark.asyncio
async def test_build_book_event_graph_with_mock_llm_per_chapter():
    drafts = [
        {
            "characters": [
                {"name": "张三", "aliases": [], "description": "青年", "mentions": ["张三推开老宅的门"]},
                {"name": "李四", "aliases": [], "description": "邻人", "mentions": ["李四从屋里走出来"]},
            ],
            "events": [
                {
                    "summary": "张三归乡",
                    "actors": ["张三"],
                    "quote_span": "张三推开老宅的门",
                    "beat_type": "铺垫",
                    "dramatic_weight": 2,
                }
            ],
            "quotes": [],
            "locations": [],
        },
        {
            "characters": [
                {"name": "张三", "aliases": [], "description": "", "mentions": ["张三找到账本"]},
                {"name": "王五", "aliases": [], "description": "账房", "mentions": ["王五承认是他经手的"]},
            ],
            "events": [
                {
                    "summary": "发现抵押",
                    "actors": ["张三", "王五"],
                    "quote_span": "张三找到账本",
                    "beat_type": "转折",
                    "dramatic_weight": 5,
                }
            ],
            "quotes": [],
            "locations": [],
        },
        {
            "characters": [
                {"name": "张三", "aliases": [], "description": "", "mentions": ["张三当众质问王五"]},
                {"name": "王五", "aliases": [], "description": "", "mentions": ["王五拿出字据"]},
            ],
            "events": [
                {
                    "summary": "当众对峙",
                    "actors": ["张三", "王五"],
                    "quote_span": "张三当众质问王五",
                    "beat_type": "高潮",
                    "dramatic_weight": 5,
                }
            ],
            "quotes": [],
            "locations": [],
        },
    ]
    llm = AsyncMock()
    llm.side_effect = [{"content": json.dumps(d, ensure_ascii=False)} for d in drafts]
    book = await build_book_event_graph(source_name="测试书", raw_text=NOVEL, llm=llm)
    assert llm.await_count == 3
    assert len(book.chapters) == 3
    assert [e.event_id for e in book.events] == ["CH01E001", "CH02E001", "CH03E001"]
    # 张三在 3 章合并为一个角色
    assert sum(1 for c in book.characters if c.name == "张三") == 1


@pytest.mark.asyncio
async def test_build_book_event_graph_deterministic_fallback_without_llm():
    """无 LLM：仍能切章并产出段落级事件（质量低但可跑通）。"""
    failing = AsyncMock(side_effect=RuntimeError("no channel"))
    book = await build_book_event_graph(source_name="测试书", raw_text=NOVEL, llm=failing)
    assert len(book.chapters) == 3
    assert len(book.events) >= 3
    assert all(e.chapter_ref for e in book.events)


def _book_with_events(n: int) -> StoryGraph:
    events = [
        StoryEvent(
            event_id=f"E{i:03d}",
            summary=f"事件{i}",
            actors=["C001"],
            beat_type="高潮" if i % 3 == 0 else "过场",
            dramatic_weight=5 if i % 3 == 0 else 1,
            chapter_ref="CH01",
        )
        for i in range(1, n + 1)
    ]
    return StoryGraph(
        meta=StoryMeta(source="book", chapter_refs=["CH01"]),
        characters=[StoryCharacter(char_id="C001", name="张三")],
        events=events,
        chapters=[StoryChapter(chapter_id="CH01", index=1, title="一", event_ids=[e.event_id for e in events])],
    )


def test_adaptation_outline_compresses_by_episode_and_duration():
    book = _book_with_events(40)
    outline = build_adaptation_outline(book, target_episodes=3, episode_duration_s=60)
    assert outline.target_episodes == 3
    assert len(outline.episodes) == 3
    # 总镜头预算 = 3 × 12 = 36
    assert outline.total_shot_budget == 36
    # 事件被压缩（40 > 容量），且保留的事件按戏剧性权重优先
    assert outline.compressed is True
    kept = [eid for ep in outline.episodes for eid in ep.event_ids]
    assert len(kept) == len(set(kept))
    by_id = {e.event_id: e for e in book.events}
    kept_set, dropped_set = set(kept), set(outline.dropped_event_ids)
    # 除首尾（保序保留）外，保留下来的事件权重不低于被丢弃的
    kept_mid = [by_id[e].dramatic_weight for e in kept_set if e not in {"E001", "E040"}]
    dropped_mid = [by_id[e].dramatic_weight for e in dropped_set if e not in {"E001", "E040"}]
    if kept_mid and dropped_mid:
        assert min(kept_mid) >= max(dropped_mid)
    # 高权重（冲突/高潮）事件一个都不该被丢
    assert not ({"E003", "E006", "E009", "E012"} & dropped_set)
    # 每集镜头预算 = 每章预算(60s → 12/2章=6)
    assert all(ep.shot_budget == 6 for ep in outline.episodes)


def test_adaptation_outline_keeps_all_when_within_budget():
    book = _book_with_events(3)
    outline = build_adaptation_outline(book, target_episodes=3, episode_duration_s=120)
    assert outline.compressed is False
    assert sum(len(ep.event_ids) for ep in outline.episodes) == 3
    assert outline.dropped_event_ids == []


def test_outline_to_story_filters_events_and_characters():
    book = _book_with_events(10)
    outline = build_adaptation_outline(book, target_episodes=2, episode_duration_s=30)
    story = outline_to_story(book, outline)
    kept = {eid for ep in outline.episodes for eid in ep.event_ids}
    assert {e.event_id for e in story.events} == kept
    assert story.adaptation_outline is not None
    assert all(c.char_id in {a for e in story.events for a in e.actors} for c in story.characters)
