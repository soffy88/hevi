from typing import Any, Protocol


class LLMCaller(Protocol):
    """LLM 调用接口. omodul 通过 obase.ProviderRegistry 获取实现, 传给 oskill."""

    def __call__(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
        stop_sequences: list[str] | None = None,
    ) -> dict[str, Any]:
        """返回 dict 含: content / stop_reason / usage / tool_calls (如适用)."""
        ...
