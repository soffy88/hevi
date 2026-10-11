"""章节事件图 —— 长篇按章抽事件、跨章合并、按集数×时长选事件生成改编大纲（DRAMAPLAN）。

并入 storygraph（不新起模块），向后兼容旧单篇 StoryGraph：
  - `split_novel_chapters`  复用 script2video 的 `novel_split.split_chapters` 切章；
  - `build_book_event_graph` 逐章抽事件（复用 `extract_story_graph` 的确定性 span/ID/幻觉守卫），
    跨章合并人物（按 canonical 名/别名）与事件（稳定全局 ID），存进 `StoryGraph.chapters`；
  - `build_adaptation_outline` 按“目标集数 × 每集时长”挑选/压缩事件 → `AdaptationOutline`，
    `outline_to_story` 落回裁剪后的 StoryGraph 接 `season_planner`；
  - 长文本上下文用 `hevi.memory.store.MemoryStore` 存章节摘要并按需召回，避免把全文塞进
    一次 LLM 调用。

每个 LLM 步骤都有确定性兜底：无 LLM（或 LLM 失败）时用段落启发式抽事件，仍能跑通，
只是质量低（事件粒度粗、无对白/因果）。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from hevi.layer4_legacy.script2video.oprim_impl.novel_split import split_chapters
from hevi.layer4_legacy.script2video.oskill_impl.shot_budget import (
    expected_chapters_for_duration,
    shot_budget_for_duration,
    shot_budget_per_chapter,
)
from hevi.storygraph.extract import extract_story_graph
from hevi.storygraph.schemas import (
    AdaptationOutline,
    OutlineEpisode,
    StoryChapter,
    StoryCharacter,
    StoryEvent,
    StoryGraph,
    StoryLocation,
    StoryMeta,
    StoryQuote,
    StoryRelationship,
)

logger = logging.getLogger(__name__)

# 每集事件数下限/上限（避免一集塞太多事件）。
MIN_EVENTS_PER_EPISODE = 1
MAX_EVENTS_PER_EPISODE = 8
# 一个事件大致折算多少镜头（用于把镜头预算换成事件容量）。
SHOTS_PER_EVENT = 2
# 确定性兜底：每章最多抽多少个段落事件。
_DETERMINISTIC_MAX_EVENTS_PER_CHAPTER = 8


def split_novel_chapters(raw_text: str) -> list[tuple[str, str]]:
    """切章 → [(title, body), ...]（复用 novel_split；无标题则整篇一章）。"""
    return split_chapters(raw_text or "")


def _deterministic_chapter_events(body: str, *, chapter_id: str) -> list[StoryEvent]:
    """无 LLM 兜底：按段落抽事件（每段首句为摘要，角色为空，权重默认）。"""
    paragraphs = [p.strip() for p in re.split(r"\n+", body or "") if p.strip()]
    if not paragraphs:
        paragraphs = [body.strip()] if body.strip() else []
    events: list[StoryEvent] = []
    for i, para in enumerate(paragraphs[:_DETERMINISTIC_MAX_EVENTS_PER_CHAPTER], start=1):
        first = re.split(r"[。！？.!?]", para, maxsplit=1)[0].strip() or para[:40]
        events.append(
            StoryEvent(
                event_id=f"{chapter_id}E{i:03d}",
                summary=first[:80],
                location=None,
                beat_type="过场",
                dramatic_weight=2,
                chapter_ref=chapter_id,
            )
        )
    return events


def _chapter_summary(body: str, *, max_chars: int = 160) -> str:
    """确定性章节摘要：取正文首段（去空白），截断。无 LLM 也能给 memory store 用。"""
    text = re.sub(r"\s+", "", body or "")
    return text[:max_chars]


async def extract_chapter_graphs(
    *,
    source_name: str,
    chapters: list[tuple[str, str]],
    llm: Any = None,
    memory_store: Any = None,
    on_chapter: Callable[[int, int, str], None] | None = None,
) -> tuple[list[StoryChapter], list[StoryGraph]]:
    """逐章抽取事件图。返回 (章节元数据列表, 逐章 StoryGraph 列表)。

    LLM 抽取失败/为空 → 该章走确定性段落兜底（保证事件图非空、可跑通）。
    每章摘要写进 memory_store（若提供），供长上下文检索。
    """
    chapter_metas: list[StoryChapter] = []
    chapter_graphs: list[StoryGraph] = []
    total = len(chapters)
    for i, (title, body) in enumerate(chapters, start=1):
        chapter_id = f"CH{i:02d}"
        summary = _chapter_summary(body)
        if on_chapter is not None:
            on_chapter(i, total, title)
        graph: StoryGraph
        try:
            graph = await extract_story_graph(
                source_name=f"{source_name}·{title}", raw_text=body, llm=llm
            )
        except Exception as exc:  # pragma: no cover - extract already degrades
            logger.warning("章节 %s 抽取异常,走确定性兜底: %s", chapter_id, exc)
            graph = StoryGraph(meta=StoryMeta(source=title, char_count=len(body)))
        if not graph.events:
            logger.info("章节 %s LLM 未产出事件,走确定性段落兜底", chapter_id)
            graph.events = _deterministic_chapter_events(body, chapter_id=chapter_id)
        for ev in graph.events:
            ev.chapter_ref = chapter_id
        chapter_metas.append(
            StoryChapter(
                chapter_id=chapter_id,
                index=i,
                title=title,
                summary=summary,
                char_count=len(body),
                event_ids=[ev.event_id for ev in graph.events],
            )
        )
        chapter_graphs.append(graph)
        if memory_store is not None:
            try:
                memory_store.remember(
                    "summary",
                    chapter_id,
                    {"title": title, "summary": summary, "chars": len(body)},
                )
            except Exception as exc:  # pragma: no cover - memory is best-effort
                logger.debug("memory_store 写章节摘要失败: %s", exc)
    return chapter_metas, chapter_graphs


def _canonical_key(char: StoryCharacter) -> str:
    """人物合并键：canonical 名去空白（别名并入 name_to_global 映射）。"""
    return char.name.strip()


def merge_chapter_graphs(
    *,
    source_name: str,
    chapter_metas: list[StoryChapter],
    chapter_graphs: list[StoryGraph],
) -> StoryGraph:
    """跨章合并为全书事件图（纯函数，便于单测）。

    - 人物：按 canonical 名/别名跨章合并到同一全局 char_id（稳定 C001…）；
    - 事件：全局 ID = `{chapter_id}E{local:03d}`（稳定、可回溯），章内 causes/effects
      重映射到全局 ID；章首无因事件补一条“上一章末事件 → 本章首事件”的跨章因果；
    - 对白/地点/关系：引用重映射到全局 ID。
    """
    global_chars: list[StoryCharacter] = []
    key_to_gid: dict[str, str] = {}
    # 逐章局部 char_id → 全局 char_id 的映射（每章一份）
    chapter_char_maps: list[dict[str, str]] = []

    for graph in chapter_graphs:
        local_map: dict[str, str] = {}
        for ch in graph.characters:
            key = _canonical_key(ch)
            gid = key_to_gid.get(key)
            if gid is None:
                gid = f"C{len(global_chars) + 1:03d}"
                key_to_gid[key] = gid
                global_chars.append(
                    StoryCharacter(
                        char_id=gid,
                        name=ch.name,
                        aliases=list(ch.aliases),
                        description=ch.description,
                        role=ch.role,
                        faction=ch.faction,
                        first_appearance=ch.first_appearance,
                        source_spans=list(ch.source_spans),
                    )
                )
            else:
                existing = next(c for c in global_chars if c.char_id == gid)
                for alias in ch.aliases:
                    if alias and alias not in existing.aliases:
                        existing.aliases.append(alias)
                if ch.description and not existing.description:
                    existing.description = ch.description
                if ch.role and not existing.role:
                    existing.role = ch.role
            for alias in (ch.name, *ch.aliases):
                key_to_gid.setdefault(alias.strip(), gid)
            local_map[ch.char_id] = gid
        chapter_char_maps.append(local_map)

    # 全局事件 ID 映射：局部 event_id → 全局 event_id
    local_to_global: list[dict[str, str]] = []
    for meta, graph in zip(chapter_metas, chapter_graphs, strict=False):
        mapping = {ev.event_id: f"{meta.chapter_id}E{j:03d}" for j, ev in enumerate(graph.events, 1)}
        local_to_global.append(mapping)

    global_events: list[StoryEvent] = []
    for ci, (meta, graph) in enumerate(zip(chapter_metas, chapter_graphs, strict=False)):
        cmap = chapter_char_maps[ci]
        emap = local_to_global[ci]
        for ev in graph.events:
            gid = emap[ev.event_id]
            actors = [cmap.get(a, a) for a in ev.actors]
            causes = [emap.get(c, c) for c in ev.causes]
            effects = [emap.get(e, e) for e in ev.effects]
            global_events.append(
                StoryEvent(
                    event_id=gid,
                    summary=ev.summary,
                    actors=actors,
                    location=ev.location,
                    time_hint=ev.time_hint,
                    causes=causes,
                    effects=effects,
                    beat_type=ev.beat_type,
                    dramatic_weight=ev.dramatic_weight,
                    source_span=ev.source_span,
                    chapter_ref=meta.chapter_id,
                    merged_from=[ev.event_id],
                )
            )

    # 跨章因果缝合：每章首事件若无 causes，且存在上一章末事件，则补一条依赖。
    first_event_by_chapter: dict[str, StoryEvent] = {}
    last_event_by_chapter: dict[str, StoryEvent] = {}
    for ev in global_events:
        first_event_by_chapter.setdefault(ev.chapter_ref, ev)
        last_event_by_chapter[ev.chapter_ref] = ev
    prev_chapter_id: str | None = None
    for meta in chapter_metas:
        cid = meta.chapter_id
        if prev_chapter_id is not None:
            first = first_event_by_chapter.get(cid)
            prev_last = last_event_by_chapter.get(prev_chapter_id)
            if first is not None and prev_last is not None and not first.causes:
                first.causes = [prev_last.event_id]
                if first.event_id not in prev_last.effects:
                    prev_last.effects.append(first.event_id)
        prev_chapter_id = cid

    # 对白：speaker/event_id 重映射
    global_quotes: list[StoryQuote] = []
    for ci, graph in enumerate(chapter_graphs):
        cmap = chapter_char_maps[ci]
        emap = local_to_global[ci]
        for q in graph.quotes:
            global_quotes.append(
                StoryQuote(
                    quote_id=f"Q{len(global_quotes) + 1:03d}",
                    speaker=cmap.get(q.speaker, q.speaker),
                    original=q.original,
                    modern=q.modern,
                    event_id=emap.get(q.event_id or "", q.event_id),
                    emotion=q.emotion,
                )
            )

    # 地点：按名合并，事件重映射
    loc_by_name: dict[str, StoryLocation] = {}
    for ci, graph in enumerate(chapter_graphs):
        emap = local_to_global[ci]
        for loc in graph.locations:
            name = loc.name.strip()
            if not name:
                continue
            existing = loc_by_name.get(name)
            if existing is None:
                existing = StoryLocation(
                    location_id=f"L{len(loc_by_name) + 1:03d}",
                    name=name,
                    type=loc.type,
                )
                loc_by_name[name] = existing
            for eid in loc.events:
                geid = emap.get(eid, eid)
                if geid and geid not in existing.events:
                    existing.events.append(geid)

    # 关系：跨章按 (from,to,type) 合并 evolution
    rel_by_key: dict[tuple[str, str, str], StoryRelationship] = {}
    for ci, graph in enumerate(chapter_graphs):
        cmap = chapter_char_maps[ci]
        emap = local_to_global[ci]
        for rel in graph.relationships:
            frm = cmap.get(rel.from_char, rel.from_char)
            to = cmap.get(rel.to_char, rel.to_char)
            key = (frm, to, rel.relation_type)
            existing = rel_by_key.get(key)
            if existing is None:
                existing = StoryRelationship(
                    from_char=frm,
                    to_char=to,
                    relation_type=rel.relation_type,
                    valence=rel.valence,
                )
                rel_by_key[key] = existing
            for step in rel.evolution:
                gstep = dict(step)
                gstep["event_id"] = emap.get(step.get("event_id", ""), step.get("event_id"))
                if gstep not in existing.evolution:
                    existing.evolution.append(gstep)

    meta = StoryMeta(
        source=source_name,
        char_count=sum(m.char_count for m in chapter_metas),
        chapter_refs=[m.chapter_id for m in chapter_metas],
    )
    return StoryGraph(
        meta=meta,
        characters=global_chars,
        relationships=list(rel_by_key.values()),
        events=global_events,
        quotes=global_quotes,
        locations=list(loc_by_name.values()),
        chapters=chapter_metas,
    )


async def build_book_event_graph(
    *,
    source_name: str,
    raw_text: str,
    llm: Any = None,
    memory_store: Any = None,
    on_chapter: Callable[[int, int, str], None] | None = None,
) -> StoryGraph:
    """长篇 → 全书事件图（切章 → 逐章抽取 → 跨章合并）。"""
    chapters = split_novel_chapters(raw_text)
    if not chapters:
        return StoryGraph(meta=StoryMeta(source=source_name, char_count=0))
    chapter_metas, chapter_graphs = await extract_chapter_graphs(
        source_name=source_name,
        chapters=chapters,
        llm=llm,
        memory_store=memory_store,
        on_chapter=on_chapter,
    )
    return merge_chapter_graphs(
        source_name=source_name, chapter_metas=chapter_metas, chapter_graphs=chapter_graphs
    )


def build_adaptation_outline(
    book: StoryGraph,
    *,
    target_episodes: int,
    episode_duration_s: float,
    max_events_per_episode: int = MAX_EVENTS_PER_EPISODE,
) -> AdaptationOutline:
    """按“目标集数 × 每集时长”从事件图挑选/压缩事件 → 改编大纲。

    - 总镜头预算 = 目标集数 × `shot_budget_for_duration(每集时长)`；
    - 事件容量 = 总预算 / `SHOTS_PER_EVENT`（每事件折算镜头数），再按集数均摊；
    - 事件超出容量时，优先保留高戏剧性权重事件（并按时间顺序），低权重“过场”事件被
      压缩进相邻事件（记入 `dropped_event_ids`）；
    - 事件按时间顺序**均分**到各集（不重排因果）。
    """
    target_episodes = max(1, int(target_episodes))
    total_budget = target_episodes * shot_budget_for_duration(episode_duration_s)
    per_ep_budget = shot_budget_per_chapter(episode_duration_s)

    events = list(book.events)
    capacity_total = max(
        target_episodes * MIN_EVENTS_PER_EPISODE,
        total_budget // max(1, SHOTS_PER_EVENT),
    )
    capacity_per_ep = max(
        MIN_EVENTS_PER_EPISODE,
        min(max_events_per_episode, per_ep_budget // max(1, SHOTS_PER_EVENT)),
    )
    capacity_total = min(capacity_total, target_episodes * capacity_per_ep)

    dropped: list[str] = []
    if len(events) > capacity_total:
        # 保序 + 保高权重：给每个事件打分，取前 capacity_total（保持原时间顺序）。
        indexed = list(enumerate(events))
        # 首尾事件保留（开场/收束对分集重要）
        must_keep = {0, len(events) - 1}
        ranked = sorted(
            indexed,
            key=lambda pair: (
                pair[0] in must_keep,
                pair[1].dramatic_weight,
                -pair[0],  # 同权重取靠前的
            ),
            reverse=True,
        )
        keep_idx = {idx for idx, _ in ranked[:capacity_total]}
        events = [ev for i, ev in indexed if i in keep_idx]
        dropped = [ev.event_id for i, ev in indexed if i not in keep_idx]

    # 均分到各集（保序）
    n = len(events)
    episodes: list[OutlineEpisode] = []
    for ep in range(1, target_episodes + 1):
        start = (ep - 1) * n // target_episodes
        end = ep * n // target_episodes
        chunk = events[start:end]
        beats = [ev.beat_type for ev in chunk if ev.beat_type]
        episodes.append(
            OutlineEpisode(
                ep_number=ep,
                title=f"第{ep}集",
                event_ids=[ev.event_id for ev in chunk],
                shot_budget=per_ep_budget,
                target_duration_s=float(episode_duration_s),
                emotion_arc="→".join(beats) if beats else "",
                summary=";".join(ev.summary for ev in chunk)[:200],
            )
        )
    return AdaptationOutline(
        story_source=book.meta.source,
        target_episodes=target_episodes,
        episode_duration_s=float(episode_duration_s),
        total_shot_budget=total_budget,
        episodes=episodes,
        dropped_event_ids=dropped,
        compressed=bool(dropped),
    )


def outline_to_story(book: StoryGraph, outline: AdaptationOutline) -> StoryGraph:
    """把改编大纲落回一个**裁剪后的 StoryGraph**，供 `season_planner.build_season_plan`。

    保留大纲覆盖的事件（按时间顺序）、其角色/地点/对白/关系；章章节元数据只保留仍有事件的章。
    """
    keep_ids = [eid for ep in outline.episodes for eid in ep.event_ids]
    keep_set = set(keep_ids)
    events = [ev for ev in book.events if ev.event_id in keep_set]
    # 保持大纲顺序（大纲已保序，但事件可能跨章，按大纲 episode 顺序重排）
    order = {eid: i for i, eid in enumerate(keep_ids)}
    events.sort(key=lambda ev: order.get(ev.event_id, len(order)))

    used_chars: set[str] = set()
    for ev in events:
        used_chars.update(ev.actors)
    characters = [c for c in book.characters if c.char_id in used_chars]
    relationships = [
        r
        for r in book.relationships
        if r.from_char in used_chars and r.to_char in used_chars
    ]
    quotes = [q for q in book.quotes if q.event_id in keep_set]
    used_locs = {ev.location for ev in events if ev.location}
    locations = [loc for loc in book.locations if loc.name in used_locs or set(loc.events) & keep_set]
    chapter_refs = {ev.chapter_ref for ev in events if ev.chapter_ref}
    chapters = [ch for ch in book.chapters if ch.chapter_id in chapter_refs]
    return StoryGraph(
        meta=book.meta.model_copy(update={"chapter_refs": [ch.chapter_id for ch in chapters]}),
        characters=characters,
        relationships=relationships,
        events=events,
        quotes=quotes,
        locations=locations,
        arcs=[],
        chapters=chapters,
        adaptation_outline=outline,
    )


__all__ = [
    "build_adaptation_outline",
    "build_book_event_graph",
    "expected_chapters_for_duration",
    "extract_chapter_graphs",
    "merge_chapter_graphs",
    "outline_to_story",
    "split_novel_chapters",
]
