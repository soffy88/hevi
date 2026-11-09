"""文本 LLM 选取:云端结构化优先,再走 TeamoRouter 免费槽,再回落本地。"""

from __future__ import annotations

from typing import Any

# S19: OpenCode Zen (opencode-go/deepseek-v4.1-flash) is the text-LLM primary;
# qwen_cloud/TeamoRouter/NIM/local stay as fallbacks. ``default`` remains the
# last resort, decided separately by provider registration policy.
TEXT_LLM_ORDER: tuple[str, ...] = (
    "opencode",
    "qwen_cloud",
    "grok",
    "pi",
    "teamo_free",
    "teamo",
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
