"""文本 LLM 选取:云端结构化优先,再走 TeamoRouter 免费槽,再回落本地。"""
from __future__ import annotations

from typing import Any

# qwen_cloud 是结构化长文本的 canonical provider；TeamoRouter 的 Grok/Pi
# 作为 fallback，local 只在云端 provider 未注册时兜底。default 仍由 provider
# registration policy 单独决定(当前可配置为 local)，不应改变显式 resolver 顺序。
TEXT_LLM_ORDER: tuple[str, ...] = (
    "qwen_cloud",
    "grok",
    "pi",
    "teamo_free",
    "teamo",
    "opencode",
    "nim",
    "local",
    "default",
)


def resolve_text_llm(llm: Any = None) -> Any:
    """取第一个已注册的文本 LLM；没有注册 provider 时返回 ``None``。

    Resolver 不应在 registry 明确为空时偷偷构造一个未注册的 local adapter：
    这样会绕过 provider readiness/isolation，也会让上层的 best-effort 降级
    无法生效。正常 production startup 会注册 local 作为显式 fallback。
    """
    if llm is not None:
        return llm
    from obase.provider_registry import ProviderRegistry

    registry = ProviderRegistry.get()
    for name in TEXT_LLM_ORDER:
        try:
            found = registry.llm(name)
        except Exception:
            continue
        if found is not None:
            return found
    return None


__all__ = ["TEXT_LLM_ORDER", "resolve_text_llm"]
