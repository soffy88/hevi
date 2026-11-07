"""oskill 统一异常 + 共享类型."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class OskillError(Exception):
    """所有 oskill 失败时抛出的基类."""

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.cause = cause


class EditOskillError(OskillError):
    """编辑/diff 类 oskill 失败."""


class ParseOskillError(OskillError):
    """解析类 oskill 失败."""


class LLMOskillError(OskillError):
    """LLM 依赖类 oskill 失败."""


class ConfigOskillError(OskillError):
    """配置类 oskill 失败."""


# ---------------------------------------------------------------------------
# 共享数据类型（跨多个 oskill 使用）
# ---------------------------------------------------------------------------


@dataclass
class EditBlock:
    """search/replace 编辑块."""

    search: str
    replace: str


@dataclass
class ApplyResult:
    """apply_edit_block / apply_unified_diff 返回值."""

    content: str
    applied: int
    conflicts: list[str] = field(default_factory=list)
    rejects: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.conflicts and not self.rejects


@dataclass
class Chunk:
    """代码/文本分块单元."""

    content: str
    start_line: int
    end_line: int
    token_count: int
    path: str = ""
    language: str = ""
    chunk_id: str = ""


@dataclass
class Symbol:
    """代码符号（函数/类/变量）."""

    name: str
    kind: str  # "function" | "class" | "variable" | "import" | ...
    start_line: int
    end_line: int
    path: str = ""
    signature: str = ""
    docstring: str = ""


@dataclass
class RepoFile:
    """repo map 中的单个文件条目."""

    path: str
    language: str
    size_bytes: int
    symbols: list[Symbol] = field(default_factory=list)
    head_lines: str = ""  # 文件头部若干行（供 LLM 快速预览）


@dataclass
class RepoMap:
    """整个代码库的结构地图."""

    root: str
    files: list[RepoFile] = field(default_factory=list)
    total_files: int = 0
    languages: dict[str, int] = field(default_factory=dict)


@dataclass
class TodoItem:
    """单个 todo 条目."""

    id: str
    content: str
    status: str = "pending"  # "pending" | "in_progress" | "done" | "cancelled"
    priority: str = "medium"  # "high" | "medium" | "low"


@dataclass
class SubTask:
    """plan_decompose 产出的子任务."""

    id: str
    title: str
    description: str
    dependencies: list[str] = field(default_factory=list)
    estimated_complexity: str = "medium"


@dataclass
class ToolCall:
    """parse_llm_tool_calls 解析出的工具调用."""

    id: str
    name: str
    input: dict[str, Any]
    raw: dict = field(default_factory=dict)


@dataclass
class PluginManifest:
    """compose_plugin_manifest 产出."""

    name: str
    version: str
    skills: list[str] = field(default_factory=list)
    subagents: list[str] = field(default_factory=list)
    commands: list[dict] = field(default_factory=list)
    hooks: list[dict] = field(default_factory=list)
    mcp_servers: list[dict] = field(default_factory=list)


@dataclass
class UndoPlan:
    """build_undo_plan 产出."""

    snapshot_rev: str
    paths: list[str]
    description: str
    can_undo: bool = True


@dataclass
class HookCmd:
    """evaluate_hooks 产出的钩子指令."""

    event: str
    command: str
    matcher: str | None = None
