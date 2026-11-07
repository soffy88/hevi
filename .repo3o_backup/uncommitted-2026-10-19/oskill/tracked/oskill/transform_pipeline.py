"""K-09 transform_pipeline — convert unified messages to provider request payload.

Composes oprim:
    - to_anthropic_format / to_openai_format / to_google_format / to_bedrock_format
    - normalize_tool_schema
    - split_system_message
    - patch_provider_quirk
    - inject_cache_control

Sync (pure algorithm). Stateless.
"""

from __future__ import annotations

from typing import Any, cast

from oprim import (
    inject_cache_control,
    normalize_tool_schema,
    patch_provider_quirk,
    split_system_message,
    to_anthropic_format,
    to_bedrock_format,
    to_google_format,
    to_openai_format,
)
from oprim._hicode_types import Message

_FORMAT_MAP = {
    "anthropic": to_anthropic_format,
    "bedrock": to_bedrock_format,
    "openai": to_openai_format,
    "google": to_google_format,
}


def transform_pipeline(
    messages: list[Message],
    *,
    provider: str,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Convert unified Message list to a provider-specific request payload.

    Composes: to_{provider}_format, normalize_tool_schema, split_system_message,
              patch_provider_quirk, inject_cache_control.

    Args:
        messages: Unified message list.
        provider: Target provider: 'anthropic', 'openai', 'google', 'bedrock'.
        tools: Optional tool definitions.

    Returns:
        Complete provider-specific request payload dict.

    Raises:
        ValueError: If provider is unknown.
    """
    if provider not in _FORMAT_MAP:
        raise ValueError(f"Unknown provider: {provider!r}")

    formatter = _FORMAT_MAP[provider]

    # Split system if needed
    system_text, remaining = split_system_message(messages, provider=provider)

    # Format messages
    payload: dict[str, Any] = cast(dict[str, Any], formatter(remaining))

    # Inject system
    if system_text:
        if provider in ("anthropic", "bedrock"):
            payload["system"] = system_text
        elif provider == "openai":
            msgs = payload.get("messages", [])
            payload["messages"] = [{"role": "system", "content": system_text}] + msgs

    # Tool schema
    if tools:
        normalized = normalize_tool_schema(tools, provider=provider)
        if provider == "google":
            payload["tools"] = [{"function_declarations": [t for t in normalized]}]
        else:
            payload["tools"] = normalized

    # Patch quirks
    payload = patch_provider_quirk(payload, provider=provider)

    # Cache control
    payload = inject_cache_control(payload, provider=provider)

    return payload
