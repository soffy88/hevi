"""Chunking strategies for RAG text processing."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Literal

import numpy as np
from oprim import vector_similarity


def chunking_strategy_apply(
    text: str,
    *,
    strategy: Literal["fixed_size", "sentence", "paragraph", "recursive", "semantic"] = "recursive",
    chunk_size: int = 512,
    chunk_overlap: int = 50,
    separators: list[str] | None = None,
    length_fn: Callable[[str], int] = len,
    embedding_fn: Callable[[str], np.ndarray] | None = None,
    semantic_threshold: float = 0.7,
) -> list[dict[str, Any]]:
    """Apply a text chunking strategy and return structured chunk dicts.

    Strategies:
        - fixed_size: Split at chunk_size char boundaries with overlap
        - sentence: Split on sentence boundaries (.!?) with overlap
        - paragraph: Split on \\n\\n
        - recursive: Try separators in order [\\n\\n, \\n, ". ", " ", ""] (LangChain pattern)
        - semantic: Requires embedding_fn; cosine similarity between adjacent sentence
          embeddings; split where similarity < semantic_threshold

    Parameters
    ----------
    text : str
        Input text to chunk.
    strategy : str
        Chunking strategy.
    chunk_size : int
        Target chunk size in characters (or length_fn units).
    chunk_overlap : int
        Overlap between consecutive chunks (in characters).
    separators : list[str] or None
        Custom separators for recursive strategy.
    length_fn : callable
        Function to measure text length. Defaults to len.
    embedding_fn : callable or None
        (str) -> np.ndarray for semantic chunking.
    semantic_threshold : float
        Cosine similarity threshold below which to split for semantic strategy.

    Returns
    -------
    list of dicts: [{content, start_index, end_index, chunk_index, metadata}]
    where metadata includes: {strategy, overlap_with_prev}

    Raises
    ------
    ValueError
        If chunk_size < 1, chunk_overlap >= chunk_size, or strategy='semantic'
        without embedding_fn.
    """
    if chunk_size < 1:
        raise ValueError(f"chunk_size must be >= 1, got {chunk_size}")
    if chunk_overlap >= chunk_size:
        raise ValueError(f"chunk_overlap ({chunk_overlap}) must be < chunk_size ({chunk_size})")
    if strategy == "semantic" and embedding_fn is None:
        raise ValueError("strategy='semantic' requires embedding_fn to be provided")

    valid_strategies = {"fixed_size", "sentence", "paragraph", "recursive", "semantic"}
    if strategy not in valid_strategies:
        raise ValueError(
            f"Unknown strategy: {strategy!r}. Must be one of {sorted(valid_strategies)}"
        )

    if not text:
        return []

    if strategy == "fixed_size":
        raw_chunks = _chunk_fixed_size(text, chunk_size, chunk_overlap, length_fn)
    elif strategy == "sentence":
        raw_chunks = _chunk_sentence(text, chunk_size, chunk_overlap, length_fn)
    elif strategy == "paragraph":
        raw_chunks = _chunk_paragraph(text)
    elif strategy == "recursive":
        seps = separators if separators is not None else ["\n\n", "\n", ". ", " ", ""]
        raw_chunks = _chunk_recursive(text, chunk_size, chunk_overlap, seps, length_fn)
    elif strategy == "semantic":
        raw_chunks = _chunk_semantic(
            text,
            embedding_fn,
            semantic_threshold,
            chunk_size,
            length_fn,  # type: ignore[arg-type]
        )
    else:
        raise ValueError(f"Unknown strategy: {strategy!r}")

    # Build structured chunk dicts
    result: list[dict[str, Any]] = []
    prev_end = -1
    for i, (content, start, end) in enumerate(raw_chunks):
        overlap_with_prev = (i > 0) and (start < prev_end)
        result.append(
            {
                "content": content,
                "start_index": start,
                "end_index": end,
                "chunk_index": i,
                "metadata": {
                    "strategy": strategy,
                    "overlap_with_prev": overlap_with_prev,
                },
            }
        )
        prev_end = end

    return result


def _chunk_fixed_size(
    text: str,
    chunk_size: int,
    overlap: int,
    length_fn: Callable[[str], int],
) -> list[tuple[str, int, int]]:
    """Split text at fixed character boundaries with overlap."""
    chunks: list[tuple[str, int, int]] = []
    start = 0
    step = chunk_size - overlap
    if step <= 0:
        step = 1

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk:
            chunks.append((chunk, start, min(end, len(text))))
        if end >= len(text):
            break
        start += step

    return chunks


def _chunk_sentence(
    text: str,
    chunk_size: int,
    overlap: int,
    length_fn: Callable[[str], int],
) -> list[tuple[str, int, int]]:
    """Split on sentence boundaries (.!?) and group into chunks."""
    # Split on sentence-ending punctuation followed by whitespace
    sentence_pattern = re.compile(r"(?<=[.!?])\s+")
    parts = sentence_pattern.split(text)

    # Find actual positions in original text
    sentences: list[tuple[str, int, int]] = []
    pos = 0
    for part in parts:
        if part:
            start = text.find(part, pos)
            if start == -1:
                start = pos
            end = start + len(part)
            sentences.append((part, start, end))
            pos = end

    if not sentences:
        return [(text, 0, len(text))]

    # Group sentences into chunks up to chunk_size
    chunks: list[tuple[str, int, int]] = []
    current_sentences: list[tuple[str, int, int]] = []
    current_len = 0

    def flush_chunk(sents: list[tuple[str, int, int]]) -> tuple[str, int, int] | None:
        if not sents:
            return None
        content = " ".join(s[0] for s in sents)
        start = sents[0][1]
        end = sents[-1][2]
        return content, start, end

    for sent in sentences:
        sent_len = length_fn(sent[0])
        if current_len + sent_len > chunk_size and current_sentences:
            chunk = flush_chunk(current_sentences)
            if chunk:
                chunks.append(chunk)
            # Overlap: keep last few sentences
            overlap_sents: list[tuple[str, int, int]] = []
            overlap_len = 0
            for s in reversed(current_sentences):
                slen = length_fn(s[0])
                if overlap_len + slen <= overlap:
                    overlap_sents.insert(0, s)
                    overlap_len += slen
                else:
                    break
            current_sentences = overlap_sents
            current_len = overlap_len

        current_sentences.append(sent)
        current_len += sent_len

    # Final chunk
    if current_sentences:
        chunk = flush_chunk(current_sentences)
        if chunk:
            chunks.append(chunk)

    return chunks if chunks else [(text, 0, len(text))]


def _chunk_paragraph(text: str) -> list[tuple[str, int, int]]:
    """Split on double newlines."""
    parts = re.split(r"\n\n+", text)
    chunks: list[tuple[str, int, int]] = []
    pos = 0
    for part in parts:
        part = part.strip()
        if part:
            start = text.find(part, pos)
            if start == -1:
                start = pos
            end = start + len(part)
            chunks.append((part, start, end))
            pos = end
    return chunks if chunks else [(text, 0, len(text))]


def _chunk_recursive(
    text: str,
    chunk_size: int,
    overlap: int,
    separators: list[str],
    length_fn: Callable[[str], int],
) -> list[tuple[str, int, int]]:
    """Recursively split using separators in order until chunks fit chunk_size."""
    if length_fn(text) <= chunk_size:
        return [(text, 0, len(text))]

    result: list[tuple[str, int, int]] = []
    _recursive_split(text, 0, chunk_size, overlap, separators, length_fn, result)
    return result if result else [(text, 0, len(text))]


def _recursive_split(
    text: str,
    offset: int,
    chunk_size: int,
    overlap: int,
    separators: list[str],
    length_fn: Callable[[str], int],
    result: list[tuple[str, int, int]],
) -> None:
    """Internal recursive helper."""
    if length_fn(text) <= chunk_size:
        if text.strip():
            result.append((text, offset, offset + len(text)))
        return

    # Try each separator
    for sep in separators:
        if sep == "":
            # Character-level split
            _split_char_level(text, offset, chunk_size, overlap, result)
            return

        parts = text.split(sep)
        if len(parts) <= 1:
            continue

        # Merge parts greedily into chunk_size
        current = ""
        current_start = 0

        for part in parts:
            candidate = current + (sep if current else "") + part
            if length_fn(candidate) <= chunk_size:
                if not current:
                    current_start = 0
                current = candidate
            else:
                if current:
                    result.append(
                        (current, offset + current_start, offset + current_start + len(current))
                    )
                    # Overlap: keep trailing characters
                    if overlap > 0 and len(current) > overlap:
                        overlap_text = current[-overlap:]
                        current = overlap_text + (sep if sep else "") + part
                        current_start = (
                            current_start + len(current) - len(overlap_text) - len(sep) - len(part)
                        )
                    else:
                        current = part
                        current_start = current_start + len(current) - len(part)
                else:
                    # Single part too big: recurse with next separator
                    next_seps = separators[separators.index(sep) + 1 :]
                    if next_seps:
                        _recursive_split(
                            part, offset, chunk_size, overlap, next_seps, length_fn, result
                        )
                    else:
                        _split_char_level(part, offset, chunk_size, overlap, result)
                    current = ""

        if current:
            result.append((current, offset + current_start, offset + current_start + len(current)))
        return

    # No separator worked, char-level fallback
    _split_char_level(text, offset, chunk_size, overlap, result)


def _split_char_level(
    text: str,
    offset: int,
    chunk_size: int,
    overlap: int,
    result: list[tuple[str, int, int]],
) -> None:
    """Character-level split fallback."""
    step = chunk_size - overlap if chunk_size > overlap else 1
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            result.append((chunk, offset + start, offset + min(end, len(text))))
        if end >= len(text):
            break
        start += step


def _chunk_semantic(
    text: str,
    embedding_fn: Callable[[str], np.ndarray],
    threshold: float,
    chunk_size: int,
    length_fn: Callable[[str], int],
) -> list[tuple[str, int, int]]:
    """Split on semantic boundaries using cosine similarity between adjacent sentences."""
    # First split into sentences
    sentence_pattern = re.compile(r"(?<=[.!?])\s+")
    parts = sentence_pattern.split(text)
    sentences = [p.strip() for p in parts if p.strip()]

    if len(sentences) <= 1:
        return [(text, 0, len(text))]

    # Compute embeddings for each sentence
    embeddings = [embedding_fn(s) for s in sentences]

    # Find split points: where similarity between adjacent sentences < threshold
    split_points: set[int] = set()
    for i in range(len(sentences) - 1):
        emb_a = embeddings[i]
        emb_b = embeddings[i + 1]
        # Use oprim.vector_similarity: query=emb_a, corpus=emb_b.reshape(1,-1)
        corpus = emb_b.reshape(1, -1)
        sim_arr = vector_similarity(emb_a, corpus=corpus, metric="cosine")
        sim = float(sim_arr[0])
        if sim < threshold:
            split_points.add(i + 1)

    # Build chunks from groups of sentences
    chunks: list[tuple[str, int, int]] = []
    current_group: list[str] = []
    pos = 0

    for i, sent in enumerate(sentences):
        if i in split_points and current_group:
            chunk_text = " ".join(current_group)
            start = text.find(chunk_text, pos)
            if start == -1:
                start = pos
            end = start + len(chunk_text)
            chunks.append((chunk_text, start, end))
            pos = end
            current_group = []
        current_group.append(sent)

    # Final group
    if current_group:
        chunk_text = " ".join(current_group)
        start = text.find(chunk_text, pos)
        if start == -1:
            start = pos
        end = start + len(chunk_text)
        chunks.append((chunk_text, start, end))

    return chunks if chunks else [(text, 0, len(text))]
