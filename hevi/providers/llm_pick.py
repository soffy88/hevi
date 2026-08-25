"""文本 LLM 选取:云端结构化优先,再走 TeamoRouter 免费槽,再回落本地。"""

from __future__ import annotations

from typing import Any

# qwen_cloud 仍优先(长剧本 JSON 最稳)。其后接 TeamoRouter 的 grok / pi / 福利版。
TEXT_LLM_ORDER: tuple[str, ...] = (
    "qwen_cloud",
    "grok",
    "pi",
    "teamo_free",
    "teamo",
    "opencode",
    "nim",
    "default",
)


def resolve_text_llm(llm: Any = None) -> Any:
    """取第一个已注册的文本 LLM。传入 llm 则原样返回。"""
    if llm is not None:
        return llm
    from obase.provider_registry import ProviderRegistry

    last: Exception | None = None
    registry = ProviderRegistry.get()
    for name in TEXT_LLM_ORDER:
        try:
            found = registry.llm(name)
        except Exception as exc:
            last = exc
            continue
        if found is not None:
            return found
    raise RuntimeError("no LLM provider registered") from last


__all__ = ["TEXT_LLM_ORDER", "resolve_text_llm"]
