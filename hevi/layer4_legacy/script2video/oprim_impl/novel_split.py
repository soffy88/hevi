"""Novel2Video 切块 / 抽取压缩 / 重叠缝合 / 简易检索。

3O 归属(待上游): `oprim.novel_split`。
ViMax: chunk 65536/8192, RAG 512/128, rerank≥0.7。
"""

from __future__ import annotations

import re

_CHAPTER = re.compile(
    r"(?:^|\n)(?:#+\s+.+|第[一二三四五六七八九十\d]+章[^\n]*)",
)
_DIALOGUE = re.compile(r"[「“].+?[」”]")
DEFAULT_CHUNK_SIZE = 65536
DEFAULT_CHUNK_OVERLAP = 8192
RAG_CHUNK_SIZE = 512
RAG_CHUNK_OVERLAP = 128
RAG_SCORE_FLOOR = 0.7


def split_chapters(text: str) -> list[tuple[str, str]]:
    """返回 [(heading, body), ...];无章节标题则整篇一章。"""
    raw = text or ""
    headings = _CHAPTER.findall(raw)
    bodies = _CHAPTER.split(raw)
    if not headings:
        return [("全文", raw.strip())] if raw.strip() else []
    # split 前可能有前言
    pairs: list[tuple[str, str]] = []
    preface = bodies[0].strip() if bodies else ""
    chapters = bodies[1:]
    if preface and not headings:
        pairs.append(("前言", preface))
    for heading, body in zip(headings, chapters, strict=False):
        title = heading.strip().lstrip("#").strip()
        pairs.append((title or "章", body.strip()))
    return [item for item in pairs if item[1]]


def split_chunks(
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    if not text:
        return []
    size = max(32, chunk_size)
    ov = max(0, min(overlap, size // 2))
    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(length, start + size)
        chunks.append(text[start:end])
        if end >= length:
            break
        start = end - ov
    return chunks


def extractive_compress_chunk(chunk: str, *, keep_ratio: float = 0.35) -> str:
    """无 LLM 时:保留对白 + 每段首句,压到 keep_ratio。"""
    if not chunk.strip():
        return ""
    kept: list[str] = []
    for para in re.split(r"\n+", chunk):
        para = para.strip()
        if not para:
            continue
        quotes = _DIALOGUE.findall(para)
        first = re.split(r"[。！？.!?]", para, maxsplit=1)[0].strip()
        if quotes:
            kept.extend(quotes)
        if first:
            kept.append(first)
    joined = " ".join(kept)
    budget = max(80, int(len(chunk) * keep_ratio))
    return joined[:budget].strip()


def stitch_overlap(chunks: list[str], *, overlap_window: int = 200) -> str:
    """后一块覆盖前一块尾部的相同前缀时丢掉重复。"""
    if not chunks:
        return ""
    acc = chunks[0]
    for nxt in chunks[1:]:
        window = min(overlap_window, len(acc), len(nxt))
        cut = 0
        for size in range(window, 3, -1):
            if acc[-size:] == nxt[:size]:
                cut = size
                break
        acc = acc + nxt[cut:]
    return acc


def _tokens(text: str) -> set[str]:
    blob = (text or "").lower()
    latin = set(re.findall(r"[a-z0-9]{2,}", blob))
    grams: set[str] = set()
    for run in re.findall(r"[\u4e00-\u9fff]+", blob):
        if len(run) <= 4:
            grams.add(run)
        grams.update(run[i : i + 2] for i in range(max(0, len(run) - 1)))
    return latin | grams


def token_overlap_score(query: str, document: str) -> float:
    q, d = _tokens(query), _tokens(document)
    if not q or not d:
        return 0.0
    return len(q & d) / len(q)


def retrieve_chunks(
    query: str,
    documents: list[str],
    *,
    top_k: int = 10,
    floor: float = RAG_SCORE_FLOOR,
) -> list[tuple[str, float]]:
    scored = [(doc, token_overlap_score(query, doc)) for doc in documents]
    scored.sort(key=lambda item: item[1], reverse=True)
    return [(doc, score) for doc, score in scored[:top_k] if score >= floor]
