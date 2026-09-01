"""Stateless contracts for a LongCat-compatible agent request."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

LONGCAT_CONTEXT_LIMIT = 1_000_000


@dataclass(frozen=True)
class LongCatContextBlock:
    """A retrievable context unit.

    ``priority`` and ``recency`` are caller-provided signals.  They let HEVI
    preserve important blocks when a repository/document is larger than the
    available request budget without pretending to reproduce model-level LSA.
    """

    block_id: str
    text: str
    kind: str = "document"
    priority: float = 0.0
    recency: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LongCatTool:
    """OpenAI-compatible function tool exposed to the agent."""

    name: str
    description: str = ""
    parameters: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.name.strip():
            errors.append("tool name is required")
        if self.name.strip() != self.name:
            errors.append("tool name must not have surrounding whitespace")
        if not isinstance(self.parameters, dict):
            errors.append(f"tool parameters must be an object: {self.name}")
        return errors

    def to_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


@dataclass(frozen=True)
class LongCatRequest:
    """Model-neutral request accepted by the LongCat agent workflow."""

    goal: str
    messages: tuple[dict[str, Any], ...] = ()
    context_blocks: tuple[LongCatContextBlock, ...] = ()
    model: str = "LongCat-2.0"
    max_context_tokens: int = 1_000_000
    max_output_tokens: int = 4096
    max_tool_rounds: int = 8
    enable_thinking: bool = True
    temperature: float = 0.2
    tools: tuple[LongCatTool, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.goal.strip() and not self.messages:
            errors.append("goal or messages is required")
        if not self.model.strip():
            errors.append("model is required")
        if not 1_024 <= self.max_context_tokens <= LONGCAT_CONTEXT_LIMIT:
            errors.append(
                f"max_context_tokens must be between 1024 and {LONGCAT_CONTEXT_LIMIT}"
            )
        if not 1 <= self.max_output_tokens <= 131_072:
            errors.append("max_output_tokens must be between 1 and 131072")
        if not 0 <= self.max_tool_rounds <= 32:
            errors.append("max_tool_rounds must be between 0 and 32")
        if not 0.0 <= self.temperature <= 2.0:
            errors.append("temperature must be between 0 and 2")
        for tool in self.tools:
            errors.extend(tool.validate())
        names = [tool.name for tool in self.tools]
        if len(names) != len(set(names)):
            errors.append("tool names must be unique")
        return errors

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["context_blocks"] = [block.to_dict() for block in self.context_blocks]
        body["tools"] = [tool.to_dict() for tool in self.tools]
        body["messages"] = [dict(message) for message in self.messages]
        return body


__all__ = [
    "LONGCAT_CONTEXT_LIMIT",
    "LongCatContextBlock",
    "LongCatRequest",
    "LongCatTool",
]
