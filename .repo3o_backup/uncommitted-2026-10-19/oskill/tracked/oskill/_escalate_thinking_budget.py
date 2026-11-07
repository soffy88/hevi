"""Auto-split from hicode whl."""

from __future__ import annotations


def escalate_thinking_budget(prompt: str) -> int | None:
    """根据 prompt 中的思考指令关键词返回 thinking token 预算（纯内存）。

    Args:
        prompt: 用户 prompt 字符串。

    Returns:
        thinking token 预算 int，或 None（无思考指令）。

    Example:
        >>> escalate_thinking_budget("ultrathink about this problem")
        31000
        >>> escalate_thinking_budget("think step by step")
        10000
        >>> escalate_thinking_budget("hello world")
        None
    """
    lower = prompt.lower()
    for keywords, budget in _THINKING_KEYWORDS:
        if any(kw in lower for kw in keywords):
            return budget
    return None


_THINKING_KEYWORDS = [
    (["ultrathink", "think very hard", "think extremely hard"], 31_000),
    (["think hard", "think carefully", "think deeply", "think step by step"], 10_000),
    (["think", "reason", "analyze", "consider", "reflect"], 5_000),
]
