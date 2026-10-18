from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EditResult:
    success: bool
    result: str = ""
    diff: str = ""
    reason: str = ""
    lsp_warnings: list[str] = field(default_factory=list)


@dataclass
class DecodedTurn:
    message: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = "end_turn"
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass
class Pos:
    line: int
    character: int


@dataclass
class IntelResult:
    hover_text: str = ""
    definition: str = ""
    references_count: int = 0
    snippet: str = ""


@dataclass
class CallNode:
    name: str
    path: str
    line: int
    incoming: list[CallNode] = field(default_factory=list)
    outgoing: list[CallNode] = field(default_factory=list)


@dataclass
class CallTree:
    root: CallNode | None = None
    depth_reached: int = 0


@dataclass
class ProjectMap:
    root: Path
    project_type: str = "unknown"
    key_files: list[str] = field(default_factory=list)
    tree: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)


@dataclass
class ResearchResult:
    query: str
    sources: list[str] = field(default_factory=list)
    summary: str = ""
    confidence: float = 0.0


@dataclass
class SubagentPlan:
    prompt: str
    tools: list[Any] = field(default_factory=list)
    summary_rule: str = ""
    persona_name: str = ""


SnapshotId = str
