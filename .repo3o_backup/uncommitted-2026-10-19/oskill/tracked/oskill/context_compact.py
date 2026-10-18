"""K-06 context_compact — LLM-driven conversation history compaction + 渐进式披露.

Composes oprim:
    - should_compact
    - select_compaction_window
    - extract_pinned_messages
    - build_compaction_prompt
    - merge_summary
    - (LLMCaller Protocol injection for summarisation)

扩展 (WAVE H, context engineering 内部扩展, 非独立 public element):
    - rank_context_items / select_context_window / compact_context / expand_item
    - 分层披露 L0 headlines -> L1 summaries -> L2 details -> L3 full source

IO-orchestration (LLM call) + 纯函数披露层. Not used as sub-call by sibling oskills.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from oprim import (
    build_compaction_prompt,
    extract_pinned_messages,  # noqa: F401
    merge_summary,
    select_compaction_window,
    should_compact,
)
from oprim._hicode_types import Message


class LLMCaller(Protocol):
    async def __call__(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
    ) -> dict[str, Any]: ...


async def context_compact(
    history: list[Message],
    *,
    caller: LLMCaller,
    budget_tokens: int,
) -> list[Message]:
    """Compact conversation history when it exceeds token budget.

    Composes: should_compact, select_compaction_window, extract_pinned_messages,
              build_compaction_prompt, merge_summary, caller (LLM injection).

    Args:
        history: Full conversation history.
        caller: LLM caller Protocol for summarisation.
        budget_tokens: Token budget threshold.

    Returns:
        Compacted history (original if no compaction needed).
    """
    if not should_compact(history, budget_tokens=budget_tokens, model=""):
        return history

    window = select_compaction_window(history)

    if not window.to_compact:
        return history

    prompt_msgs = build_compaction_prompt(window)
    response = await caller(messages=prompt_msgs, max_tokens=1024)

    # Extract summary text from response
    summary = ""
    content = response.get("content", "")
    if isinstance(content, str):
        summary = content
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                summary = block.get("text", "")
                break

    return cast(list[Message], merge_summary(summary, tail=window.to_keep))


# ── WAVE H: progressive context disclosure (context engineering extension) ──

LAYER_ORDER = ("L0", "L1", "L2", "L3")
_LAYER_RANK = {layer: idx for idx, layer in enumerate(LAYER_ORDER)}


@dataclass
class ContextItem:
    """可披露上下文条目。"""

    item_id: str
    headline: str = ""
    summary: str = ""
    detail: str = ""
    source_text: str = ""
    layer: str = "L0"  # 当前已披露层 L0..L3
    token_cost: int = 0  # 当前层 token 成本
    relevance: float = 0.5  # 0..1
    recency: float = 0.5  # 0..1 (越新越大)
    source: str = ""
    expandable: bool = True
    pinned: bool = False  # 高优先级:永不丢弃
    extra: dict[str, Any] = field(default_factory=dict)


def _layer_of(item: ContextItem) -> int:
    return _LAYER_RANK.get(item.layer, 0)


def rank_context_items(
    items: list[ContextItem], *, relevance_weight: float = 0.6, recency_weight: float = 0.4
) -> list[ContextItem]:
    """确定性排序: relevance/recency 加权减层成本惩罚 (stable sort)。"""
    scored = []
    for idx, item in enumerate(items):
        cost_penalty = _layer_of(item) * 0.05 + min(item.token_cost / 10000.0, 0.5)
        score = (
            relevance_weight * item.relevance
            + recency_weight * item.recency
            - cost_penalty
            + (10.0 if item.pinned else 0.0)
        )
        scored.append((score, idx, item))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [item for _, _, item in scored]


def select_context_window(
    items: list[ContextItem], token_budget: int, *, must_include: list[str] | None = None
) -> list[ContextItem]:
    """token budget 内贪心选窗: pinned/must_include 优先,其余按分值密度。

    高优先级永不丢弃 (budget 不足则只返回 pinned + must_include)。
    """
    if token_budget < 0:
        raise ValueError("select_context_window: token_budget must be >= 0")
    must = set(must_include or [])
    ranked = rank_context_items(items)
    selected: list[ContextItem] = []
    used = 0
    # 第一遍: pinned + must_include (原始相对顺序)
    for item in items:
        if item.pinned or item.item_id in must:
            if item not in selected:
                selected.append(item)
                used += item.token_cost
    # 第二遍:按排名贪心填充
    for item in ranked:
        if item in selected:
            continue
        if used + item.token_cost <= token_budget:
            selected.append(item)
            used += item.token_cost
    return selected


def _content_at_layer(item: ContextItem, layer: str) -> tuple[str, int]:
    if layer == "L0":
        return item.headline, max(1, len(item.headline) // 4)
    if layer == "L1":
        text = item.summary or item.headline
        return text, max(1, len(text) // 4)
    if layer == "L2":
        text = item.detail or item.summary or item.headline
        return text, max(1, len(text) // 4)
    text = item.source_text or item.detail or item.summary or item.headline
    return text, max(1, len(text) // 4)


def expand_item(item: ContextItem, target_layer: str) -> ContextItem:
    """确定性切换到目标披露层 (向上展开需 expandable,向下折叠恒允许)。"""
    if target_layer not in _LAYER_RANK:
        raise ValueError(f"expand_item: unknown layer {target_layer}")
    if _LAYER_RANK[target_layer] > _layer_of(item) and not item.expandable:
        return item
    if target_layer == item.layer:
        return item
    text, cost = _content_at_layer(item, target_layer)
    return ContextItem(
        item_id=item.item_id,
        headline=item.headline,
        summary=item.summary,
        detail=item.detail,
        source_text=item.source_text,
        layer=target_layer,
        token_cost=cost,
        relevance=item.relevance,
        recency=item.recency,
        source=item.source,
        expandable=item.expandable,
        pinned=item.pinned,
        extra={"expanded_text": text, **item.extra},
    )


def compact_context(items: list[ContextItem], token_budget: int) -> list[ContextItem]:
    """渐进压缩: L3->L2->L1 逐层降级, L0 headline 常留; pinned 永不丢弃。

    确定性:同输入同 budget 同输出;总成本恒 <= budget (pinned 超限除外)。
    """
    ranked = rank_context_items(items)
    # 先全部降到 L0,计算基线
    base = [expand_item(item, "L0") if _layer_of(item) > 0 else item for item in ranked]
    # pinned 超限也保留 (如实返回,调用方可感知超限)
    total = sum(i.token_cost for i in base)
    if total <= token_budget:
        current = list(base)
    else:
        current = [i for i in base if i.pinned]
        total = sum(i.token_cost for i in current)
        # budget 连 pinned 都装不下:仍返回 pinned (不丢高优先级)
        if total > token_budget:
            return current
    # 逐层展开:按排名逐个 L0->L1->L2->L3,装得下就升
    order = {item.item_id: pos for pos, item in enumerate(ranked)}
    current_by_id = {i.item_id: i for i in current}
    for item in ranked:
        if item.item_id not in current_by_id:
            continue
        for layer in ("L1", "L2", "L3"):
            candidate = expand_item(current_by_id[item.item_id], layer)
            delta = candidate.token_cost - current_by_id[item.item_id].token_cost
            if total + delta <= token_budget:
                current_by_id[item.item_id] = candidate
                total += delta
            else:
                break
    result = list(current_by_id.values())
    result.sort(key=lambda i: order.get(i.item_id, 0))
    return result
