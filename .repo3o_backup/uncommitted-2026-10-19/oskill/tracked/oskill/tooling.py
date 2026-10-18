"""
oskill: 工具/配置/hook 算法组（纯内存）
=========================================
format_diagnostics / parse_llm_tool_calls / select_tools / merge_config
evaluate_hooks / match_permission_rule / escalate_thinking_budget
plan_to_todos / apply_todo_update / compose_plugin_manifest
build_subagent_prompt / merge_subagent_result

全部 stateless 纯算法，不持久化。
"""

from __future__ import annotations

import fnmatch
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

from ._types import (
    ConfigOskillError,
    OskillError,
    ParseOskillError,
    PluginManifest,
    TodoItem,
    ToolCall,
)

# ---------------------------------------------------------------------------
# format_diagnostics
# ---------------------------------------------------------------------------


def format_diagnostics(
    diagnostics: list[Any],
    *,
    max_per_file: int = 20,
    include_source: bool = True,
) -> str:
    """将诊断列表格式化为人类可读字符串（纯内存）。

    Args:
        diagnostics: Diagnostic 对象列表（或 dict 列表，含 path/line/message/severity）。
        max_per_file: 每个文件最多显示条数，默认 20。
        include_source: 是否显示 source 字段，默认 True。

    Returns:
        格式化字符串，按文件分组、按严重程度着色。

    Example:
        >>> text = format_diagnostics(diags)
        >>> "error" in text.lower()
        True
    """
    if not diagnostics:
        return "No diagnostics."

    _SEV = {1: "ERROR", 2: "WARN ", 3: "INFO ", 4: "HINT "}
    by_file: dict[str, list] = {}
    for d in diagnostics:
        path = getattr(d, "path", None) or (d.get("path", "") if isinstance(d, dict) else "")
        by_file.setdefault(path, []).append(d)

    parts = []
    for path, items in sorted(by_file.items()):
        parts.append(f"\n{path}:")
        for item in items[:max_per_file]:
            if hasattr(item, "line"):
                line, char = item.line + 1, item.character  # pragma: no cover
                sev = _SEV.get(item.severity, "?    ")  # pragma: no cover
                msg = item.message  # pragma: no cover
                src = (
                    f" [{item.source}]" if include_source and item.source else ""
                )  # pragma: no cover
            else:
                line = item.get("line", 0) + 1
                char = item.get("character", 0)
                sev = _SEV.get(item.get("severity", 1), "?    ")
                msg = item.get("message", "")
                src = f" [{item['source']}]" if include_source and item.get("source") else ""
            parts.append(f"  {sev} {line}:{char}  {msg}{src}")
        if len(items) > max_per_file:
            parts.append(f"  ... and {len(items) - max_per_file} more")

    return "\n".join(parts).strip()


# ---------------------------------------------------------------------------
# parse_llm_tool_calls
# ---------------------------------------------------------------------------


def parse_llm_tool_calls(
    response: dict[str, Any],
) -> list[ToolCall]:
    """从 LLM 响应中解析并校验 tool_use 块列表（纯内存）。

    Args:
        response: LLM 原始响应 dict（含 content 列表）。

    Returns:
        ToolCall 列表（已校验 name + input 字段）。

    Raises:
        ParseOskillError: content 字段格式错误。

    Example:
        >>> calls = parse_llm_tool_calls({"content": [
        ...     {"type": "tool_use", "id": "t1", "name": "bash_exec", "input": {"cmd": "ls"}}
        ... ]})
        >>> calls[0].name
        'bash_exec'
    """
    content = response.get("content", [])
    if not isinstance(content, list):
        raise ParseOskillError(
            f"parse_llm_tool_calls: content must be list, got {type(content).__name__}"
        )

    calls = []
    for block in content:
        if not isinstance(block, dict):
            continue  # pragma: no cover
        if block.get("type") != "tool_use":
            continue
        name = block.get("name", "")
        if not name:
            continue
        tool_id = block.get("id") or str(uuid.uuid4())[:8]
        inp = block.get("input", {})
        if not isinstance(inp, dict):
            # 尝试 JSON 解析
            try:  # pragma: no cover
                inp = json.loads(inp) if isinstance(inp, str) else {}  # pragma: no cover
            except (json.JSONDecodeError, TypeError):  # pragma: no cover
                inp = {}  # pragma: no cover
        calls.append(ToolCall(id=tool_id, name=name, input=inp, raw=block))
    return calls


# ---------------------------------------------------------------------------
# select_tools
# ---------------------------------------------------------------------------


@dataclass
class ToolScore:
    name: str
    score: float
    reason: str


def select_tools(
    task: str,
    *,
    available: list[dict[str, Any]],
    max_tools: int = 10,
    mode: str = "build",
) -> list[dict[str, Any]]:
    """根据任务描述和模式选择最相关的工具子集（纯内存）。

    策略：关键词匹配 + 模式过滤（plan 模式排除写操作工具）。

    Args:
        task: 任务描述字符串。
        available: 工具 schema 列表（含 name / description）。
        max_tools: 最多返回工具数，默认 10。
        mode: "build" 或 "plan"。

    Returns:
        排序后的工具 schema 子集（最多 max_tools 个）。

    Example:
        >>> tools = select_tools("read a file", available=[...], mode="plan")
        >>> all(t["name"] != "file_write" for t in tools)
        True  # plan 模式排除写操作
    """
    WRITE_TOOLS = {
        "file_write",
        "file_append",
        "file_delete",
        "bash_exec",
        "git_add",
        "git_commit",
        "git_stash",
    }
    task_lower = task.lower()
    task_words = set(re.findall(r"\w+", task_lower))

    scored: list[ToolScore] = []
    for tool in available:
        name = tool.get("name", "")
        desc = tool.get("description", "").lower()

        # plan 模式过滤写操作
        if mode == "plan" and name in WRITE_TOOLS:
            continue

        # 关键词匹配评分
        tool_words = set(re.findall(r"\w+", name.lower() + " " + desc))
        overlap = task_words & tool_words
        score = len(overlap) / max(len(task_words), 1)

        # 名称直接匹配加分
        if any(w in name.lower() for w in task_words):
            score += 0.5

        scored.append(ToolScore(name=name, score=score, reason=f"overlap={len(overlap)}"))

    scored.sort(key=lambda s: s.score, reverse=True)
    selected_names = {s.name for s in scored[:max_tools]}
    return [t for t in available if t.get("name") in selected_names]


# ---------------------------------------------------------------------------
# merge_config
# ---------------------------------------------------------------------------


def merge_config(
    global_: dict[str, Any],
    project: dict[str, Any],
    agents_md: dict[str, Any] | None = None,
    *,
    env_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """分层合并配置（纯内存）。

    优先级（高→低）：env_overrides > agents_md > project > global_

    Args:
        global_: 全局配置 dict。
        project: 项目级配置 dict。
        agents_md: AGENTS.md 解析出的配置 dict（可选）。
        env_overrides: 环境变量覆盖 dict（最高优先级，可选）。

    Returns:
        合并后的有效配置 dict。

    Example:
        >>> cfg = merge_config({"model": "opus"}, {"model": "sonnet"})
        >>> cfg["model"]
        'sonnet'  # 项目级覆盖全局
    """
    result: dict[str, Any] = {}
    for src in [global_, project, agents_md or {}, env_overrides or {}]:
        if isinstance(src, dict):
            result.update(src)
    return result


# ---------------------------------------------------------------------------
# evaluate_hooks
# ---------------------------------------------------------------------------

from ._types import HookCmd


@dataclass
class _OldHookCmd:
    event: str
    command: str
    matcher: str | None


def evaluate_hooks(
    event: str,
    payload: dict[str, Any],
    *,
    hook_specs: list[dict[str, Any]],
) -> list[HookCmd]:
    """评估哪些 hook 在此事件 + payload 上触发（纯内存）。

    实际执行由调用方调 run_hook oprim 完成，oskill 只做"应该触发哪些"的纯判断。

    Args:
        event: 事件名，如 "PreToolUse"。
        payload: 事件 payload，含 tool / type 等字段。
        hook_specs: hook 定义列表，每项含 event / command / matcher（可选 glob）。

    Returns:
        应触发的 HookCmd 列表（已过滤 + 排序）。

    Example:
        >>> cmds = evaluate_hooks("PreToolUse", {"tool": "bash_exec"},
        ...     hook_specs=[{"event": "PreToolUse", "command": "/hook.sh", "matcher": "bash_*"}])
        >>> len(cmds)
        1
    """
    tool_name = payload.get("tool", payload.get("type", ""))
    matched: list[HookCmd] = []

    for spec in hook_specs:
        if spec.get("event") != event:
            continue
        matcher = spec.get("matcher")
        command = spec.get("command", "")
        if not command:
            continue
        if matcher is None or fnmatch.fnmatch(tool_name, matcher):
            matched.append(HookCmd(event=event, command=command, matcher=matcher))

    return matched


# ---------------------------------------------------------------------------
# match_permission_rule
# ---------------------------------------------------------------------------


def match_permission_rule(
    tool_call: dict[str, Any],
    *,
    allowed_tools: list[str] | None = None,
    denied_tools: list[str] | None = None,
    mode: str = "default",
) -> str:
    """权限决策算法（纯内存）。

    返回 "allow" | "deny" | "ask"。

    优先级：denied > allowed > mode 规则 > ask。

    Args:
        tool_call: 含 name 字段的工具调用 dict。
        allowed_tools: 允许的工具名 glob 模式列表。
        denied_tools: 拒绝的工具名 glob 模式列表。
        mode: "default" | "acceptEdits" | "plan" | "bypass"。

    Returns:
        "allow" | "deny" | "ask"

    Example:
        >>> match_permission_rule({"name": "bash_exec"}, mode="plan")
        'deny'
    """
    name = tool_call.get("name", "")
    READ_ONLY = {
        "file_read",
        "dir_list",
        "glob_match",
        "git_status",
        "git_diff",
        "git_log",
        "git_show",
        "git_blame",
        "lsp_diagnostics",
        "lsp_hover",
        "lsp_definition",
        "lsp_references",
        "lsp_document_symbols",
        "lsp_workspace_symbols",
        "lsp_completion",
        "ripgrep_search",
    }

    if mode == "bypass":
        return "allow"

    if mode == "plan":
        return "allow" if name in READ_ONLY else "deny"

    # denied 列表
    for pattern in denied_tools or []:
        if fnmatch.fnmatch(name, pattern):
            return "deny"

    # allowed 列表
    for pattern in allowed_tools or []:
        if fnmatch.fnmatch(name, pattern):
            return "allow"

    if mode == "acceptEdits":
        if name in {"file_write", "file_append", "file_delete"}:
            return "allow"

    return "ask"


# ---------------------------------------------------------------------------
# escalate_thinking_budget
# ---------------------------------------------------------------------------

_THINKING_KEYWORDS: list[tuple[list[str], int]] = [
    (["ultrathink", "think very hard", "think extremely hard"], 31_000),
    (["think hard", "think carefully", "think deeply", "think step by step"], 10_000),
    (["think", "reason", "analyze", "consider", "reflect"], 5_000),
]


def escalate_thinking_budget(prompt: str) -> int | None:
    """根据 prompt 中的思考指令关键词返回 thinking token 预算（纯内存）。

    Args:
        prompt: 用户 prompt 字符串。

    Returns:
        thinking token 预算 int，或 None（无思考指令）。

    Example:
        >>> escalate_thinking_budget("ultrathink about this problem")
        31000
        >>> escalate_thinking_budget("think step by step")
        10000
        >>> escalate_thinking_budget("hello world")
        None
    """
    lower = prompt.lower()
    for keywords, budget in _THINKING_KEYWORDS:
        if any(kw in lower for kw in keywords):
            return budget
    return None


# ---------------------------------------------------------------------------
# plan_to_todos
# ---------------------------------------------------------------------------


def plan_to_todos(
    plan: list[dict[str, Any]] | str,
    *,
    priority_map: dict[str, str] | None = None,
) -> list[TodoItem]:
    """将计划（SubTask 列表或文本）转为 TodoItem 列表（纯内存）。

    Args:
        plan: SubTask dict 列表，或文本字符串（每行一个 todo）。
        priority_map: task title → priority 覆盖映射。

    Returns:
        TodoItem 列表，id 自动生成。

    Example:
        >>> todos = plan_to_todos([{"title": "Write tests", "description": "..."}])
        >>> todos[0].content
        'Write tests'
        >>> todos[0].status
        'pending'
    """
    pm = priority_map or {}
    todos: list[TodoItem] = []

    if isinstance(plan, str):
        for line in plan.strip().splitlines():
            line = line.strip().lstrip("-*•123456789. ")
            if not line:
                continue
            tid = f"todo_{uuid.uuid4().hex[:8]}"
            todos.append(
                TodoItem(
                    id=tid,
                    content=line,
                    status="pending",
                    priority=pm.get(line, "medium"),
                )
            )
        return todos

    for item in plan:
        if isinstance(item, dict):
            title = item.get("title") or item.get("content", "")
            tid = item.get("id") or f"todo_{uuid.uuid4().hex[:8]}"
            todos.append(
                TodoItem(
                    id=tid,
                    content=title,
                    status=item.get("status", "pending"),
                    priority=pm.get(title, item.get("priority", "medium")),
                )
            )
    return todos


# ---------------------------------------------------------------------------
# apply_todo_update
# ---------------------------------------------------------------------------


def apply_todo_update(
    todos: list[TodoItem],
    *,
    todo_id: str,
    status: str | None = None,
    content: str | None = None,
    priority: str | None = None,
) -> list[TodoItem]:
    """更新单个 todo 的状态/内容/优先级（纯内存状态机）。

    Args:
        todos: 当前 TodoItem 列表。
        todo_id: 要更新的 todo id。
        status: 新状态（可选）。
        content: 新内容（可选）。
        priority: 新优先级（可选）。

    Returns:
        更新后的 TodoItem 列表（不可变风格：返回新列表）。

    Raises:
        OskillError: todo_id 不存在或状态值不合法。

    Example:
        >>> updated = apply_todo_update(todos, todo_id="t1", status="done")
        >>> next(t for t in updated if t.id == "t1").status
        'done'
    """
    VALID_STATUSES = {"pending", "in_progress", "done", "cancelled"}
    VALID_PRIORITIES = {"high", "medium", "low"}

    if status and status not in VALID_STATUSES:
        raise OskillError(f"invalid status '{status}': must be one of {VALID_STATUSES}")
    if priority and priority not in VALID_PRIORITIES:
        raise OskillError(f"invalid priority '{priority}': must be one of {VALID_PRIORITIES}")

    updated = []
    found = False
    for todo in todos:
        if todo.id == todo_id:
            found = True
            updated.append(
                TodoItem(
                    id=todo.id,
                    content=content if content is not None else todo.content,
                    status=status if status is not None else todo.status,
                    priority=priority if priority is not None else todo.priority,
                )
            )
        else:
            updated.append(todo)

    if not found:
        raise OskillError(f"todo_id '{todo_id}' not found")
    return updated


# ---------------------------------------------------------------------------
# compose_plugin_manifest
# ---------------------------------------------------------------------------


def compose_plugin_manifest(
    bundle: dict[str, Any],
) -> PluginManifest:
    """解析插件 bundle dict 为 PluginManifest（纯内存）。

    Args:
        bundle: 插件定义 dict，含 name/version/skills/subagents/commands/hooks/mcp_servers。

    Returns:
        PluginManifest（已校验必填字段）。

    Raises:
        ConfigOskillError: name 字段缺失。

    Example:
        >>> manifest = compose_plugin_manifest({
        ...     "name": "my_plugin", "version": "1.0",
        ...     "skills": ["refactor_python"],
        ... })
        >>> manifest.name
        'my_plugin'
    """
    name = bundle.get("name", "")
    if not name:
        raise ConfigOskillError("compose_plugin_manifest: 'name' field is required")

    return PluginManifest(
        name=name,
        version=str(bundle.get("version", "0.1.0")),
        skills=_to_str_list(bundle.get("skills", [])),
        subagents=_to_str_list(bundle.get("subagents", [])),
        commands=_to_dict_list(bundle.get("commands", [])),
        hooks=_to_dict_list(bundle.get("hooks", [])),
        mcp_servers=_to_dict_list(bundle.get("mcp_servers", [])),
    )


def _to_str_list(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v]
    return []  # pragma: no cover


def _to_dict_list(v: Any) -> list[dict]:
    if isinstance(v, list):
        return [x for x in v if isinstance(x, dict)]
    return []  # pragma: no cover


# ---------------------------------------------------------------------------
# build_subagent_prompt
# ---------------------------------------------------------------------------


def build_subagent_prompt(
    subagent_def: dict[str, Any],
    task: str,
    *,
    context: str = "",
    memory: str = "",
) -> dict[str, Any]:
    """根据 subagent 定义生成系统 prompt 和受限工具集（纯内存）。

    Args:
        subagent_def: subagent 定义 dict（含 system_prompt / tools / permissions）。
        task: 主 agent 传递的任务描述。
        context: 主 agent 传递的上下文片段（可选）。
        memory: agent-memory 历史记忆内容（可选）。

    Returns:
        {
            "system": str,           # 完整系统 prompt
            "scoped_tools": list,    # 按 permissions 过滤后的工具 schema
        }

    Example:
        >>> result = build_subagent_prompt(
        ...     {"system_prompt": "You are a tester.", "tools": [...]},
        ...     task="Write unit tests",
        ... )
        >>> "tester" in result["system"]
        True
    """
    base_system = subagent_def.get("system_prompt", "You are a helpful subagent.")
    parts = [base_system.strip()]

    if memory and memory.strip():
        parts.append(f"## Historical Memory\n{memory.strip()}")
    if context and context.strip():
        parts.append(f"## Context from Parent Agent\n{context.strip()}")

    system = "\n\n".join(parts)
    permissions = subagent_def.get("permissions", {})
    mode = permissions.get("mode", "default") if isinstance(permissions, dict) else "default"
    all_tools = subagent_def.get("tools", [])

    # 按 permissions.mode 过滤工具
    READ_ONLY_NAMES = {
        "file_read",
        "dir_list",
        "glob_match",
        "git_status",
        "git_diff",
        "git_log",
        "lsp_diagnostics",
        "lsp_hover",
    }
    if mode == "plan":
        scoped = [t for t in all_tools if t.get("name") in READ_ONLY_NAMES]
    elif mode == "bypass":
        scoped = list(all_tools)
    else:
        allowed = permissions.get("allowed_tools", []) if isinstance(permissions, dict) else []
        denied = permissions.get("denied_tools", []) if isinstance(permissions, dict) else []
        scoped = []
        for tool in all_tools:
            name = tool.get("name", "")
            if any(fnmatch.fnmatch(name, p) for p in denied):
                continue  # pragma: no cover
            if not allowed or any(fnmatch.fnmatch(name, p) for p in allowed):
                scoped.append(tool)

    return {"system": system, "scoped_tools": scoped}


# ---------------------------------------------------------------------------
# merge_subagent_result
# ---------------------------------------------------------------------------


def merge_subagent_result(
    summaries: list[dict[str, Any]],
    *,
    task: str = "",
    max_length: int = 8000,
) -> str:
    """将多个 subagent 返回的摘要合并为主 agent context delta（纯内存）。

    Args:
        summaries: run_subagent 返回的 dict 列表（含 summary / subagent_name / status）。
        task: 原始任务描述（用于摘要标题）。
        max_length: 合并结果最大字符数，超出时截断。

    Returns:
        合并后的上下文字符串（注入主 agent messages）。

    Example:
        >>> ctx = merge_subagent_result([
        ...     {"subagent_name": "tester", "summary": "Tests written.", "status": "completed"}
        ... ])
        >>> "tester" in ctx
        True
    """
    if not summaries:
        return ""

    parts: list[str] = []
    if task:
        parts.append(f"## Subagent Results for: {task}\n")

    for r in summaries:
        name = r.get("subagent_name", "unknown")
        status = r.get("status", "unknown")
        summary = r.get("summary", "")
        cost = r.get("cost_usd", 0.0)
        iters = r.get("iterations", 0)
        meta = f"[{status}, {iters} iters, ${cost:.4f}]"
        parts.append(f"### {name} {meta}\n{summary}")

    result = "\n\n".join(parts)
    if len(result) > max_length:
        result = result[:max_length] + "\n...[truncated]"
    return result
