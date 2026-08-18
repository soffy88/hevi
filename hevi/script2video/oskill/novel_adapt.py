"""长篇 → 压缩 → 事件链 → 场景剧本 → 小说级角色账本。

组合: novel_split 切块/压缩/检索 + character_fuse 合并。
3O 归属(待上游): `oskill.novel_adapt`。
"""

from __future__ import annotations

from hevi.script2video.adapter_schemas import (
    LengthBudget,
    NovelCharacterBook,
    NovelEvent,
    NovelScene,
)
from hevi.script2video.oprim.character_fuse import (
    canonical_identifier,
    merge_feature_text,
    should_split_identities,
)
from hevi.script2video.oprim.idea_parse import extract_name_candidates, slugify
from hevi.script2video.oprim.novel_split import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    RAG_CHUNK_OVERLAP,
    RAG_CHUNK_SIZE,
    extractive_compress_chunk,
    retrieve_chunks,
    split_chunks,
    stitch_overlap,
)
from hevi.script2video.schemas import KernelCharacter

_MAX_EVENTS = 50
_MAX_SCENES_PER_EVENT = 5


def compress_novel(text: str) -> tuple[str, float]:
    chunks = split_chunks(text, chunk_size=DEFAULT_CHUNK_SIZE, overlap=DEFAULT_CHUNK_OVERLAP)
    compressed_parts = [extractive_compress_chunk(chunk) for chunk in chunks]
    compressed = stitch_overlap(compressed_parts)
    ratio = (len(compressed) / len(text)) if text else 0.0
    return compressed, ratio


def extract_events(compressed: str, *, max_events: int = _MAX_EVENTS) -> list[NovelEvent]:
    """无 LLM:按段落组成因果链,每事件 3 步,封顶 max_events。"""
    paras = [p.strip() for p in compressed.split("\n") if p.strip()]
    if not paras:
        paras = [compressed.strip()] if compressed.strip() else []
    if not paras:
        return []
    events: list[NovelEvent] = []
    step = 3
    chunks = [paras[i : i + step] for i in range(0, len(paras), step)]
    chunks = chunks[: max(1, max_events)]
    for index, group in enumerate(chunks):
        names = extract_name_candidates(" ".join(group))
        events.append(
            NovelEvent(
                index=index,
                description=group[0][:160],
                process_chain=group,
                is_last=index == len(chunks) - 1,
                characters=names[:6],
                location=_guess_location(group[0]),
            )
        )
    events[-1].is_last = True
    return events


def retrieve_for_event(event: NovelEvent, novel_text: str) -> list[str]:
    docs = split_chunks(novel_text, chunk_size=RAG_CHUNK_SIZE, overlap=RAG_CHUNK_OVERLAP)
    hits: dict[str, float] = {}
    for process in event.process_chain:
        for chunk, score in retrieve_chunks(process, docs):
            hits[chunk] = hits.get(chunk, 0.0) + score
    ranked = sorted(hits.items(), key=lambda item: item[1], reverse=True)
    return [chunk for chunk, _score in ranked[:12]]


def scenes_for_event(
    event: NovelEvent,
    chunks: list[str],
    *,
    max_scenes: int = _MAX_SCENES_PER_EVENT,
) -> list[NovelScene]:
    source = chunks or event.process_chain
    if not source:
        source = [event.description]
    if len(source) > max_scenes:
        head, tail = source[: max_scenes - 1], source[max_scenes - 1 :]
        source = [*head, " ".join(tail)]
    scenes: list[NovelScene] = []
    names = event.characters or extract_name_candidates(" ".join(source))
    characters = [
        KernelCharacter(name=name, identifier=slugify(name), description=name) for name in names
    ]
    for idx, text in enumerate(source[:max_scenes]):
        scenes.append(
            NovelScene(
                event_index=event.index,
                idx=idx,
                is_last=idx == min(len(source), max_scenes) - 1,
                slugline=f"INT./EXT. {event.location or 'SCENE'} - DAY",
                script=text,
                characters=characters,
                relevant_chunks=chunks,
            )
        )
    if scenes:
        scenes[-1].is_last = True
    return scenes


def merge_character_book(scenes: list[NovelScene]) -> list[NovelCharacterBook]:
    book: dict[str, NovelCharacterBook] = {}
    for scene in scenes:
        for char in scene.characters:
            ident = canonical_identifier(char.identifier or char.name)
            existing = book.get(ident)
            if existing and should_split_identities(existing.static_features, char.description):
                ident = f"{ident}_{scene.event_index}_{scene.idx}"
                existing = None
            if existing is None:
                existing = NovelCharacterBook(
                    identifier=ident,
                    name=char.name,
                    static_features=char.description,
                )
                book[ident] = existing
            else:
                existing.static_features = merge_feature_text(
                    existing.static_features, char.description
                )
            existing.active_events[scene.event_index] = char.identifier
            existing.active_scenes[f"{scene.event_index}:{scene.idx}"] = char.identifier
    return list(book.values())


def plan_novel_adaptation(
    novel_text: str,
    *,
    budget: LengthBudget | None = None,
) -> tuple[str, float, list[NovelEvent], list[NovelScene], list[NovelCharacterBook]]:
    budget = budget or LengthBudget()
    compressed, ratio = compress_novel(novel_text)
    events = extract_events(compressed, max_events=budget.max_events)
    scenes: list[NovelScene] = []
    for event in events:
        chunks = retrieve_for_event(event, novel_text)
        scenes.extend(
            scenes_for_event(event, chunks, max_scenes=budget.max_scenes_per_event)
        )
    book = merge_character_book(scenes)
    return compressed, ratio, events, scenes, book


def _guess_location(text: str) -> str:
    for token in ("咖啡馆", "街道", "公园", "房间", "大厅", "gym", "street", "park"):
        if token in text.lower():
            return token
    return "LOCATION"
