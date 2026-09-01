"""Deterministic long-context selection primitives.

The model's sparse-attention kernels are not application code.  What HEVI can
own is the surrounding context discipline: stable block IDs, relevance
ranking, budget accounting, and an auditable selection manifest.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from hevi.longcat.oprim.contracts import LongCatContextBlock

_WORD_RE = re.compile(r"[\w\u3400-\u9fff]+", re.UNICODE)


def estimate_tokens(text: str) -> int:
    """Estimate request tokens without requiring a tokenizer package.

    CJK characters are counted more conservatively than Latin words.  This is
    a routing estimate only; the provider remains the final token authority.
    """

    if not text:
        return 0
    cjk = sum("\u3400" <= char <= "\u9fff" for char in text)
    non_cjk = len(text) - cjk
    return max(1, math.ceil(cjk / 1.7 + non_cjk / 4.0))


def _terms(text: str) -> set[str]:
    return {item.lower() for item in _WORD_RE.findall(text) if item.strip()}


def _relevance(goal_terms: set[str], text: str) -> float:
    if not goal_terms:
        return 0.0
    overlap = len(goal_terms & _terms(text))
    return min(1.0, overlap / max(1, min(8, len(goal_terms))))


def _score(goal_terms: set[str], block: LongCatContextBlock) -> float:
    relevance = _relevance(goal_terms, block.text)
    return (
        0.50 * relevance
        + 0.30 * max(0.0, min(1.0, block.priority))
        + 0.20 * max(0.0, min(1.0, block.recency))
    )


def rank_context_blocks(
    goal: str, blocks: Sequence[LongCatContextBlock]
) -> list[tuple[LongCatContextBlock, float]]:
    """Rank blocks with stable tie-breaking by input order."""

    terms = _terms(goal)
    ranked = [(block, _score(terms, block)) for block in blocks if block.text.strip()]
    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked


@dataclass(frozen=True)
class ContextPack:
    blocks: tuple[LongCatContextBlock, ...]
    used_tokens: int
    budget_tokens: int
    dropped_block_ids: tuple[str, ...]
    selection_scores: dict[str, float]
    fingerprint: str

    def as_message(self) -> dict[str, str] | None:
        if not self.blocks:
            return None
        chunks = [
            f"[context:{block.block_id} kind={block.kind}]\n{block.text}"
            for block in self.blocks
        ]
        return {
            "role": "system",
            "content": (
                "HEVI context pack. Treat these as source material; preserve "
                "block IDs when citing decisions.\n\n" + "\n\n".join(chunks)
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_ids": [block.block_id for block in self.blocks],
            "used_tokens": self.used_tokens,
            "budget_tokens": self.budget_tokens,
            "dropped_block_ids": list(self.dropped_block_ids),
            "selection_scores": dict(self.selection_scores),
            "fingerprint": self.fingerprint,
        }


def pack_context(
    goal: str,
    blocks: Sequence[LongCatContextBlock],
    *,
    max_tokens: int = 1_000_000,
) -> ContextPack:
    """Select a deterministic, budget-safe context pack.

    High-scoring blocks are selected first, then returned in original order so
    narrative/code context remains readable.  Oversized blocks are truncated
    to the remaining budget and marked in the selection manifest.
    """

    if max_tokens < 1:
        raise ValueError("max_tokens must be positive")
    ranked = rank_context_blocks(goal, blocks)
    selected: list[LongCatContextBlock] = []
    scores: dict[str, float] = {}
    used = 0
    dropped: list[str] = []
    for block, score in ranked:
        block_tokens = estimate_tokens(block.text)
        if used >= max_tokens:
            dropped.append(block.block_id)
            continue
        if max_tokens - used < 2:
            dropped.append(block.block_id)
            continue
        if block_tokens <= max_tokens - used:
            chosen = block
        else:
            # Character slicing is deliberately conservative and deterministic.
            remaining_chars = max(1, int((max_tokens - used) * 3.2))
            text = block.text[:remaining_chars]
            while estimate_tokens(text) > max_tokens - used and len(text) > 1:
                text = text[: max(1, len(text) - max(1, len(text) // 20))]
            chosen = LongCatContextBlock(
                block_id=block.block_id,
                text=text,
                kind=block.kind,
                priority=block.priority,
                recency=block.recency,
                metadata={**block.metadata, "truncated": True},
            )
        selected.append(chosen)
        scores[chosen.block_id] = round(score, 6)
        used += estimate_tokens(chosen.text)
        if used >= max_tokens:
            selected_ids = {item.block_id for item in selected}
            dropped.extend(item.block_id for item, _ in ranked if item.block_id not in selected_ids)
            break
    selected.sort(key=lambda item: next(i for i, original in enumerate(blocks) if original.block_id == item.block_id))
    shape = {
        "blocks": [(item.block_id, estimate_tokens(item.text)) for item in selected],
        "dropped": dropped,
        "budget": max_tokens,
    }
    fingerprint = hashlib.sha256(repr(shape).encode("utf-8")).hexdigest()[:24]
    return ContextPack(
        blocks=tuple(selected),
        used_tokens=used,
        budget_tokens=max_tokens,
        dropped_block_ids=tuple(dict.fromkeys(dropped)),
        selection_scores=scores,
        fingerprint=fingerprint,
    )


__all__ = ["ContextPack", "estimate_tokens", "pack_context", "rank_context_blocks"]
