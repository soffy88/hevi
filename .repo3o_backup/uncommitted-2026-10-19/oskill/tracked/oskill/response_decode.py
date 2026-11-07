"""K-08 response_decode — decode LLM raw response to structured DecodedTurn.

Composes oprim:
    - parse_tool_calls
    - parse_stop_reason
    - from_anthropic_format / from_openai_format / from_google_format

Sync (pure algorithm). Stateless.
"""

from __future__ import annotations

from typing import Any

from oprim import (
    from_anthropic_format,
    from_google_format,
    from_openai_format,
    parse_stop_reason,
    parse_tool_calls,
)

from ._hc_types import DecodedTurn


def response_decode(raw: dict[str, Any], *, provider: str) -> DecodedTurn:
    """Decode a provider-specific LLM response to a unified DecodedTurn.

    Composes: parse_tool_calls, parse_stop_reason,
              from_anthropic_format / from_openai_format / from_google_format.

    Args:
        raw: Raw LLM response dict.
        provider: Provider name: 'anthropic', 'openai', or 'google'.

    Returns:
        DecodedTurn with message, tool_calls, stop_reason, usage.
    """
    # Parse tool calls
    try:
        tool_calls_raw = parse_tool_calls(raw, provider=provider)
        tool_calls = [{"id": tc.id, "name": tc.name, "args": tc.args} for tc in tool_calls_raw]
    except Exception:
        tool_calls = []

    # Parse stop reason
    try:
        stop_reason = parse_stop_reason(raw, provider=provider)
    except Exception:
        stop_reason = "end_turn"

    # Parse message
    msg_dict: dict[str, Any] = {}
    try:
        if provider == "anthropic":
            msg = from_anthropic_format(raw)
        elif provider == "openai":
            # openai: typically raw is choices[0].message
            choice = raw.get("choices", [{}])[0]
            msg = from_openai_format(choice.get("message", raw))
        elif provider == "google":
            candidate = raw.get("candidates", [{}])[0]
            msg = from_google_format(candidate.get("content", raw))
        else:
            msg = from_anthropic_format(raw)
        msg_dict = {"role": msg.role, "parts": [p.type for p in msg.parts]}
    except Exception:
        msg_dict = {"role": "assistant", "parts": []}

    # Usage
    usage: dict[str, Any] = raw.get("usage", {})

    return DecodedTurn(
        message=msg_dict,
        tool_calls=tool_calls,
        stop_reason=stop_reason,
        usage=usage,
    )
