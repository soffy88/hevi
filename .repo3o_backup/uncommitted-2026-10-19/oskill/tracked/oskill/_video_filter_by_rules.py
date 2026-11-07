"""K-1: video_filter_by_rules — rule-based + optional LLM video filtering.

Composes:
- oprim.video_filter_rules (P-4): deterministic rule filter
- LLMCaller (injected, optional): per-video semantic filter via llm_filter description

title_exclude from FilterRules runs in P-4 before any LLM step.
"""

from __future__ import annotations

import asyncio
from typing import Any

from oprim._media_types import FilterRules, VideoMeta
from oprim._video_filter_rules import video_filter_rules


async def video_filter_by_rules(
    videos: list[VideoMeta],
    *,
    rules: FilterRules,
    llm: Any | None = None,
) -> list[VideoMeta]:
    """Filter videos using deterministic rules then optional LLM semantic filter.

    Step 1: Apply video_filter_rules (after_date, duration, title_include/exclude, limit).
            title_exclude is applied here, before LLM, so it always takes priority.
    Step 2: If rules.llm_filter is set and llm is not None, call LLM for each remaining
            video to decide keep (YES) / reject (NO) based on llm_filter description.

    Args:
        videos: Input list of VideoMeta.
        rules: FilterRules dataclass with all filter parameters.
        llm: Optional LLM caller. If None or rules.llm_filter is None, LLM step is skipped.

    Returns:
        Filtered list of VideoMeta.

    Raises:
        Any exception from video_filter_rules (e.g. ValueError for bad after_date).
        Any exception from the LLM caller propagates as-is.
    """
    if not videos:
        return []

    # Step 1: deterministic rule filter (title_exclude is applied here)
    filtered = video_filter_rules(
        videos,
        after_date=rules.after_date,
        limit=rules.limit,
        min_duration=rules.min_duration,
        max_duration=rules.max_duration,
        title_include=rules.title_include or None,
        title_exclude=rules.title_exclude or None,
    )

    # Step 2: LLM semantic filter (skipped if llm is None or llm_filter is unset)
    if filtered and rules.llm_filter and llm is not None:
        filtered = await _llm_filter(filtered, llm_filter=rules.llm_filter, llm=llm)

    return filtered


# ---------------------------------------------------------------------------
# LLM filtering helpers
# ---------------------------------------------------------------------------


async def _llm_filter(
    videos: list[VideoMeta],
    *,
    llm_filter: str,
    llm: Any,
) -> list[VideoMeta]:
    """Call LLM once per video; keep only those where response starts with YES."""
    tasks = [_ask_llm(v, llm_filter=llm_filter, llm=llm) for v in videos]
    decisions = await asyncio.gather(*tasks)
    return [v for v, keep in zip(videos, decisions) if keep]


async def _ask_llm(video: VideoMeta, *, llm_filter: str, llm: Any) -> bool:
    prompt = (
        f"Filter rule: {llm_filter}\n"
        f"Video title: {video.title}\n"
        f"Description: {(video.description or '')[:500]}\n\n"
        "Should this video be included according to the filter rule? "
        "Reply YES or NO only."
    )
    messages = [{"role": "user", "content": prompt}]
    coro_or_result = llm(messages=messages, max_tokens=8)
    if asyncio.iscoroutine(coro_or_result):
        response = await coro_or_result
    else:
        response = coro_or_result

    text = _extract_text(response).strip().upper()
    return text.startswith("YES")


def _extract_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    if not isinstance(response, dict):
        return str(response)
    content = response.get("content", "")
    if isinstance(content, str):
        return content
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            return block.get("text", "")
    return ""
