"""Normalise OpenAI-compatible LongCat responses at the HEVI boundary."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.call_id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }


@dataclass(frozen=True)
class ModelTurn:
    content: str = ""
    reasoning_content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    usage: dict[str, Any] = field(default_factory=dict)
    raw_message: dict[str, Any] = field(default_factory=dict)

    @property
    def is_final(self) -> bool:
        return not self.tool_calls


def _content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            str(item.get("text") or "") if isinstance(item, dict) else str(item)
            for item in value
        )
    return "" if value is None else str(value)


def _arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {"_raw": value}
    return parsed if isinstance(parsed, dict) else {"_value": parsed}


def normalize_model_turn(raw: Any) -> ModelTurn:
    """Accept a provider response, adapter response, or already-normalised turn."""

    if isinstance(raw, ModelTurn):
        return raw
    if not isinstance(raw, dict):
        return ModelTurn(content=str(raw or ""))
    choices = raw.get("choices") or []
    message = choices[0].get("message", {}) if choices and isinstance(choices[0], dict) else {}
    if not message and ("content" in raw or "tool_calls" in raw):
        message = raw
    calls: list[ToolCall] = []
    for index, item in enumerate(message.get("tool_calls") or []):
        if not isinstance(item, dict):
            continue
        function = item.get("function") or {}
        name = str(function.get("name") or item.get("name") or "").strip()
        if not name:
            continue
        calls.append(
            ToolCall(
                call_id=str(item.get("id") or f"call-{index + 1}"),
                name=name,
                arguments=_arguments(function.get("arguments", item.get("arguments"))),
            )
        )
    usage = raw.get("usage") or {}
    return ModelTurn(
        content=_content(message.get("content")),
        reasoning_content=_content(
            message.get("reasoning_content")
            or message.get("reasoning")
            or raw.get("reasoning_content")
        ),
        tool_calls=tuple(calls),
        usage=dict(usage) if isinstance(usage, dict) else {},
        raw_message=dict(message) if isinstance(message, dict) else {},
    )


__all__ = ["ModelTurn", "ToolCall", "normalize_model_turn"]
