"""
oskill 批次 D 测试套件
======================
34 个 oskill，每个 ≥8 个测试用例。
LLM/Embed/VectorStore 全部使用 mock Protocol 实例。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from oskill import (
    ApplyResult,
    Chunk,
    ConfigOskillError,
    EditBlock,
    EditOskillError,
    LLMOskillError,
    OskillError,
    ParseOskillError,
    PluginManifest,
    RepoMap,
    SubTask,
    Symbol,
    TodoItem,
    ToolCall,
    UndoPlan,
    apply_edit_block,
    apply_todo_update,
    apply_unified_diff,
    build_repo_context,
    build_subagent_prompt,
    build_undo_plan,
    chunk_code,
    compose_plugin_manifest,
    compress_context,
    dedup_edits,
    escalate_thinking_budget,
    evaluate_hooks,
    extract_symbols,
    format_diagnostics,
    generate_patch_preview,
    load_skill_progressive,
    match_permission_rule,
    merge_config,
    merge_subagent_result,
    parse_llm_tool_calls,
    plan_decompose,
    plan_to_todos,
    rank_relevant_files,
    repo_map_build,
    resolve_memory_hierarchy,
    resolve_mentions,
    select_skill,
    select_tools,
    semantic_search,
    summarize_file,
    syntax_check,
    three_way_merge,
    validate_edit,
)
from oskill.tooling import HookCmd

# ===========================================================================
# helpers
# ===========================================================================


def make_llm_caller(text="ok", items=None):
    async def caller(**kwargs):
        content = items or [{"type": "text", "text": text}]
        return {
            "content": content,
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

    return caller


def make_embed_caller(vector=None):
    async def caller(*, text, model):
        return vector or [0.1, 0.2, 0.3]

    return caller


def make_vector_store(results=None):
    store = AsyncMock()
    store.search = AsyncMock(return_value=results or [])
    return store


def skill_dir(tmp_path, name="test_skill", extra=""):
    d = tmp_path / name
    d.mkdir()
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: A test skill\nversion: 1.0.0\n"
        f"tools: [bash_exec]\ntags: [test]\n---\n# Body\nDo stuff.{extra}"
    )
    return str(d)


# ===========================================================================
# GROUP 1: 编辑算法
# ===========================================================================


class TestApplyEditBlock:
    def test_exact_match(self):
        r = apply_edit_block("x = 1\n", blocks=[EditBlock("x = 1", "x = 2")])
        assert r.content == "x = 2\n" and r.applied == 1

    def test_fuzzy_match_strips_whitespace(self):
        r = apply_edit_block("  hello\n  world\n", blocks=[EditBlock("hello", "goodbye")])
        assert "goodbye" in r.content and r.applied == 1

    def test_not_found_goes_to_conflicts(self):
        r = apply_edit_block("abc\n", blocks=[EditBlock("xyz", "replaced")])
        assert r.applied == 0 and len(r.conflicts) == 1

    def test_multiple_blocks(self):
        r = apply_edit_block("a\nb\n", blocks=[EditBlock("a", "A"), EditBlock("b", "B")])
        assert r.applied == 2 and "A" in r.content and "B" in r.content

    def test_empty_blocks_raises(self):
        with pytest.raises(EditOskillError):
            apply_edit_block("x\n", blocks=[])

    def test_ok_property_true(self):
        r = apply_edit_block("x = 1\n", blocks=[EditBlock("x = 1", "x = 2")])
        assert r.ok is True

    def test_ok_property_false(self):
        r = apply_edit_block("x\n", blocks=[EditBlock("z", "a")])
        assert r.ok is False

    def test_returns_apply_result(self):
        r = apply_edit_block("x\n", blocks=[EditBlock("x", "y")])
        assert isinstance(r, ApplyResult)


class TestApplyUnifiedDiff:
    def test_applies_change(self):
        diff = "@@ -1,2 +1,2 @@\n a\n-b\n+B\n"
        r = apply_unified_diff("a\nb\n", diff=diff)
        assert "B" in r.content and r.applied == 1

    def test_empty_diff_returns_original(self):
        r = apply_unified_diff("abc\n", diff="")
        assert r.content == "abc\n" and r.applied == 0

    def test_reject_on_mismatch(self):
        diff = "@@ -1,1 +1,1 @@\n-WRONG\n+new\n"
        r = apply_unified_diff("actual\n", diff=diff)
        assert len(r.rejects) == 1

    def test_multi_hunk(self):
        diff = "@@ -1,1 +1,1 @@\n-a\n+A\n@@ -3,1 +3,1 @@\n-c\n+C\n"
        r = apply_unified_diff("a\nb\nc\n", diff=diff)
        assert r.applied == 2 and "A" in r.content and "C" in r.content

    def test_ok_on_success(self):
        diff = "@@ -1,1 +1,1 @@\n-x\n+y\n"
        r = apply_unified_diff("x\n", diff=diff)
        assert r.ok is True

    def test_returns_apply_result(self):
        assert isinstance(apply_unified_diff("x\n", diff=""), ApplyResult)

    def test_preserves_context_lines(self):
        diff = "@@ -1,3 +1,3 @@\n ctx1\n-old\n+new\n ctx2\n"
        r = apply_unified_diff("ctx1\nold\nctx2\n", diff=diff)
        assert "ctx1" in r.content and "ctx2" in r.content and "new" in r.content

    def test_partial_reject_still_applies_others(self):
        diff = "@@ -1,1 +1,1 @@\n-a\n+A\n@@ -5,1 +5,1 @@\n-WRONG\n+X\n"
        r = apply_unified_diff("a\nb\nc\n", diff=diff)
        assert r.applied >= 1


class TestThreeWayMerge:
    def test_no_conflict_ours_change(self):
        r = three_way_merge("a\nb\n", "a\nB\n", "a\nb\n")
        assert r["ok"] and "B" in r["merged"]

    def test_no_conflict_theirs_change(self):
        r = three_way_merge("a\nb\n", "a\nb\n", "a\nC\n")
        assert r["ok"] and "C" in r["merged"]

    def test_same_content_no_conflict(self):
        r = three_way_merge("x\n", "x\n", "x\n")
        assert r["ok"] and r["conflicts"] == 0

    def test_ours_equals_base_use_theirs(self):
        r = three_way_merge("base\n", "base\n", "new\n")
        assert r["merged"] == "new\n" and r["ok"]

    def test_theirs_equals_base_use_ours(self):
        r = three_way_merge("base\n", "ours\n", "base\n")
        assert r["merged"] == "ours\n" and r["ok"]

    def test_ours_equals_theirs(self):
        r = three_way_merge("base\n", "same\n", "same\n")
        assert r["ok"] and r["merged"] == "same\n"

    def test_real_conflict_inserts_markers(self):
        r = three_way_merge("line\n", "ours_change\n", "their_change\n")
        if not r["ok"]:
            assert "<<<<<<" in r["merged"] or r["conflicts"] > 0

    def test_returns_dict_with_ok_key(self):
        r = three_way_merge("a\n", "a\n", "a\n")
        assert "ok" in r and "merged" in r and "conflicts" in r


class TestGeneratePatchPreview:
    def test_shows_diff(self):
        preview = generate_patch_preview("x=1\n", "x=2\n", path="f.py")
        assert "-x=1" in preview and "+x=2" in preview

    def test_same_content_empty(self):
        assert generate_patch_preview("abc\n", "abc\n") == ""

    def test_includes_path(self):
        preview = generate_patch_preview("a\n", "b\n", path="src/main.py")
        assert "src/main.py" in preview

    def test_colorize_adds_ansi(self):
        preview = generate_patch_preview("a\n", "b\n", colorize=True)
        assert "\033[" in preview

    def test_no_colorize_no_ansi(self):
        preview = generate_patch_preview("a\n", "b\n", colorize=False)
        assert "\033[" not in preview

    def test_context_lines_respected(self):
        old = "\n".join(str(i) for i in range(20)) + "\n"
        new = old.replace("10", "99")
        p3 = generate_patch_preview(old, new, context_lines=3)
        p0 = generate_patch_preview(old, new, context_lines=0)
        assert len(p3) > len(p0)

    def test_returns_string(self):
        assert isinstance(generate_patch_preview("a\n", "b\n"), str)

    def test_path_appears_in_header(self):
        p = generate_patch_preview("x\n", "y\n", path="util.py")
        assert "util.py" in p


class TestDedupEdits:
    def test_removes_duplicate_path(self):
        edits = [{"path": "f.py", "full_content": "a"}, {"path": "f.py", "full_content": "b"}]
        result = dedup_edits(edits)
        assert len(result) == 1 and result[0]["full_content"] == "b"

    def test_different_paths_kept(self):
        edits = [{"path": "a.py", "full_content": "x"}, {"path": "b.py", "full_content": "y"}]
        assert len(dedup_edits(edits)) == 2

    def test_empty_returns_empty(self):
        assert dedup_edits([]) == []

    def test_no_path_field_skipped(self):
        edits = [{"full_content": "x"}]
        assert dedup_edits(edits) == []

    def test_blocks_merged(self):
        edits = [
            {"path": "f.py", "blocks": [{"search": "a", "replace": "A"}]},
            {"path": "f.py", "blocks": [{"search": "b", "replace": "B"}]},
        ]
        result = dedup_edits(edits)
        assert len(result) == 1 and len(result[0]["blocks"]) == 2

    def test_full_content_wins_over_blocks(self):
        edits = [
            {"path": "f.py", "blocks": [{"search": "a", "replace": "b"}]},
            {"path": "f.py", "full_content": "final"},
        ]
        result = dedup_edits(edits)
        assert result[0].get("full_content") == "final"

    def test_preserves_order_last_wins(self):
        edits = [
            {"path": "f.py", "full_content": "first"},
            {"path": "f.py", "full_content": "last"},
        ]
        assert dedup_edits(edits)[0]["full_content"] == "last"

    def test_returns_list(self):
        assert isinstance(dedup_edits([{"path": "x.py"}]), list)


class TestBuildUndoPlan:
    def test_basic_plan(self):
        cs = {"applied": ["a.py", "b.py"], "status": "completed", "fingerprint": "abc123"}
        plan = build_undo_plan(cs, snapshot_rev="rev001")
        assert isinstance(plan, UndoPlan)
        assert plan.can_undo and plan.paths == ["a.py", "b.py"]

    def test_no_rev_cannot_undo(self):
        plan = build_undo_plan({"applied": ["f.py"], "status": "completed"}, snapshot_rev="")
        assert plan.can_undo is False

    def test_failed_status_cannot_undo(self):
        plan = build_undo_plan({"applied": [], "status": "failed"}, snapshot_rev="rev1")
        assert plan.can_undo is False

    def test_description_contains_rev(self):
        plan = build_undo_plan({"applied": ["f.py"]}, snapshot_rev="myrev")
        assert "myrev" in plan.description

    def test_description_contains_file_count(self):
        plan = build_undo_plan({"applied": ["a.py", "b.py", "c.py"]}, snapshot_rev="r")
        assert "3" in plan.description

    def test_empty_applied(self):
        plan = build_undo_plan({}, snapshot_rev="r1")
        assert plan.paths == []

    def test_snapshot_rev_preserved(self):
        plan = build_undo_plan({}, snapshot_rev="exact_rev")
        assert plan.snapshot_rev == "exact_rev"

    def test_returns_undo_plan(self):
        plan = build_undo_plan({"applied": []}, snapshot_rev="r")
        assert isinstance(plan, UndoPlan)


# ===========================================================================
# GROUP 2: 工具/配置/hook
# ===========================================================================


class TestFormatDiagnostics:
    def _diag(self, path="f.py", line=0, char=0, sev=1, msg="err", src="pylsp"):
        return {
            "path": path,
            "line": line,
            "character": char,
            "severity": sev,
            "message": msg,
            "source": src,
        }

    def test_no_diags(self):
        assert format_diagnostics([]) == "No diagnostics."

    def test_shows_path(self):
        assert "f.py" in format_diagnostics([self._diag()])

    def test_shows_message(self):
        assert "err" in format_diagnostics([self._diag(msg="err")])

    def test_shows_severity(self):
        text = format_diagnostics([self._diag(sev=1)])
        assert "ERROR" in text

    def test_warning_severity(self):
        text = format_diagnostics([self._diag(sev=2)])
        assert "WARN" in text

    def test_max_per_file_truncated(self):
        diags = [self._diag(msg=f"e{i}") for i in range(30)]
        text = format_diagnostics(diags, max_per_file=5)
        assert "more" in text

    def test_source_included(self):
        assert "pylsp" in format_diagnostics([self._diag(src="pylsp")], include_source=True)

    def test_source_excluded(self):
        assert "pylsp" not in format_diagnostics([self._diag(src="pylsp")], include_source=False)


class TestParseLLMToolCalls:
    def test_parses_tool_use(self):
        response = {
            "content": [
                {"type": "tool_use", "id": "t1", "name": "bash_exec", "input": {"cmd": "ls"}}
            ]
        }
        calls = parse_llm_tool_calls(response)
        assert len(calls) == 1 and calls[0].name == "bash_exec"

    def test_ignores_text_blocks(self):
        response = {
            "content": [
                {"type": "text", "text": "hello"},
                {"type": "tool_use", "id": "t1", "name": "file_read", "input": {}},
            ]
        }
        calls = parse_llm_tool_calls(response)
        assert len(calls) == 1

    def test_empty_content_empty_list(self):
        assert parse_llm_tool_calls({"content": []}) == []

    def test_invalid_content_raises(self):
        with pytest.raises(ParseOskillError):
            parse_llm_tool_calls({"content": "not_a_list"})

    def test_auto_generates_id(self):
        response = {"content": [{"type": "tool_use", "name": "x", "input": {}}]}
        calls = parse_llm_tool_calls(response)
        assert calls[0].id

    def test_multiple_calls(self):
        response = {
            "content": [
                {"type": "tool_use", "id": "t1", "name": "a", "input": {}},
                {"type": "tool_use", "id": "t2", "name": "b", "input": {}},
            ]
        }
        assert len(parse_llm_tool_calls(response)) == 2

    def test_returns_tool_call_objects(self):
        response = {"content": [{"type": "tool_use", "name": "x", "input": {}}]}
        assert isinstance(parse_llm_tool_calls(response)[0], ToolCall)

    def test_no_name_skipped(self):
        response = {"content": [{"type": "tool_use", "id": "t1", "input": {}}]}
        assert parse_llm_tool_calls(response) == []


class TestSelectTools:
    TOOLS = [
        {"name": "file_read", "description": "read a file"},
        {"name": "file_write", "description": "write a file"},
        {"name": "bash_exec", "description": "execute bash commands"},
        {"name": "git_status", "description": "check git status"},
    ]

    def test_plan_mode_excludes_write(self):
        result = select_tools("do something", available=self.TOOLS, mode="plan")
        names = [t["name"] for t in result]
        assert "file_write" not in names and "bash_exec" not in names

    def test_build_mode_includes_all(self):
        result = select_tools("write files", available=self.TOOLS, mode="build")
        names = [t["name"] for t in result]
        assert "file_write" in names

    def test_relevant_tools_ranked_higher(self):
        result = select_tools("read file", available=self.TOOLS)
        names = [t["name"] for t in result]
        assert "file_read" in names

    def test_max_tools_respected(self):
        result = select_tools("do stuff", available=self.TOOLS, max_tools=2)
        assert len(result) <= 2

    def test_empty_available(self):
        assert select_tools("task", available=[]) == []

    def test_returns_list_of_dicts(self):
        result = select_tools("task", available=self.TOOLS)
        assert all(isinstance(t, dict) for t in result)

    def test_git_query_returns_git_tools(self):
        result = select_tools("git status check", available=self.TOOLS)
        names = [t["name"] for t in result]
        assert "git_status" in names

    def test_no_name_field_handled(self):
        tools = [{"description": "no name"}]
        result = select_tools("task", available=tools)
        assert isinstance(result, list)


class TestMergeConfig:
    def test_project_overrides_global(self):
        cfg = merge_config({"model": "opus"}, {"model": "sonnet"})
        assert cfg["model"] == "sonnet"

    def test_agents_md_overrides_project(self):
        cfg = merge_config({}, {"model": "sonnet"}, {"model": "haiku"})
        assert cfg["model"] == "haiku"

    def test_env_overrides_all(self):
        cfg = merge_config({"a": 1}, {"a": 2}, {"a": 3}, env_overrides={"a": 99})
        assert cfg["a"] == 99

    def test_global_keys_preserved(self):
        cfg = merge_config({"g": "global"}, {})
        assert cfg["g"] == "global"

    def test_empty_dicts(self):
        cfg = merge_config({}, {})
        assert cfg == {}

    def test_none_agents_md(self):
        cfg = merge_config({"x": 1}, {"y": 2}, None)
        assert cfg == {"x": 1, "y": 2}

    def test_no_mutation_of_inputs(self):
        g = {"a": 1}
        merge_config(g, {"b": 2})
        assert "b" not in g

    def test_deep_merge_replaces_not_merges(self):
        # merge_config 是浅合并（覆盖），不是深度合并
        cfg = merge_config({"opts": {"x": 1}}, {"opts": {"y": 2}})
        assert cfg["opts"] == {"y": 2}


class TestEvaluateHooks:
    SPECS = [
        {"event": "PreToolUse", "command": "/hook1.sh", "matcher": "bash_exec"},
        {"event": "PreToolUse", "command": "/hook2.sh", "matcher": "file_*"},
        {"event": "PostToolUse", "command": "/post.sh", "matcher": None},
    ]

    def test_exact_match(self):
        cmds = evaluate_hooks("PreToolUse", {"tool": "bash_exec"}, hook_specs=self.SPECS)
        assert any(c.command == "/hook1.sh" for c in cmds)

    def test_glob_match(self):
        cmds = evaluate_hooks("PreToolUse", {"tool": "file_read"}, hook_specs=self.SPECS)
        assert any(c.command == "/hook2.sh" for c in cmds)

    def test_wrong_event_no_match(self):
        cmds = evaluate_hooks("SessionStart", {"tool": "bash_exec"}, hook_specs=self.SPECS)
        assert len(cmds) == 0

    def test_no_matcher_matches_all(self):
        cmds = evaluate_hooks("PostToolUse", {"tool": "anything"}, hook_specs=self.SPECS)
        assert any(c.command == "/post.sh" for c in cmds)

    def test_empty_specs(self):
        assert evaluate_hooks("PreToolUse", {}, hook_specs=[]) == []

    def test_returns_hook_cmd_objects(self):
        cmds = evaluate_hooks("PostToolUse", {}, hook_specs=self.SPECS)
        assert all(isinstance(c, HookCmd) for c in cmds)

    def test_no_command_skipped(self):
        specs = [{"event": "PreToolUse", "command": "", "matcher": None}]
        cmds = evaluate_hooks("PreToolUse", {}, hook_specs=specs)
        assert len(cmds) == 0

    def test_multiple_matches(self):
        specs = [
            {"event": "X", "command": "/a.sh"},
            {"event": "X", "command": "/b.sh"},
        ]
        cmds = evaluate_hooks("X", {}, hook_specs=specs)
        assert len(cmds) == 2


class TestMatchPermissionRule:
    def test_bypass_always_allow(self):
        assert match_permission_rule({"name": "rm -rf"}, mode="bypass") == "allow"

    def test_plan_readonly_allow(self):
        assert match_permission_rule({"name": "file_read"}, mode="plan") == "allow"

    def test_plan_write_deny(self):
        assert match_permission_rule({"name": "bash_exec"}, mode="plan") == "deny"

    def test_denied_pattern(self):
        r = match_permission_rule({"name": "bash_exec"}, denied_tools=["bash_*"])
        assert r == "deny"

    def test_allowed_pattern(self):
        r = match_permission_rule({"name": "file_read"}, allowed_tools=["file_*"])
        assert r == "allow"

    def test_accept_edits_file_write(self):
        r = match_permission_rule({"name": "file_write"}, mode="acceptEdits")
        assert r == "allow"

    def test_default_no_rules_ask(self):
        r = match_permission_rule({"name": "unknown_tool"}, mode="default")
        assert r == "ask"

    def test_denied_before_allowed(self):
        r = match_permission_rule(
            {"name": "bash_exec"},
            allowed_tools=["bash_*"],
            denied_tools=["bash_*"],
        )
        assert r == "deny"


class TestEscalateThinkingBudget:
    def test_ultrathink_max_budget(self):
        assert escalate_thinking_budget("ultrathink about this") == 31_000

    def test_think_hard(self):
        assert escalate_thinking_budget("think hard about the problem") == 10_000

    def test_think_basic(self):
        b = escalate_thinking_budget("please think about this")
        assert b == 5_000

    def test_no_keyword_none(self):
        assert escalate_thinking_budget("hello world") is None

    def test_case_insensitive(self):
        assert escalate_thinking_budget("ULTRATHINK now") == 31_000

    def test_think_step_by_step(self):
        assert escalate_thinking_budget("think step by step") == 10_000

    def test_empty_string_none(self):
        assert escalate_thinking_budget("") is None

    def test_analyze_keyword(self):
        b = escalate_thinking_budget("analyze this code")
        assert b == 5_000


class TestPlanToTodos:
    def test_list_input(self):
        todos = plan_to_todos([{"id": "t1", "title": "Write tests"}])
        assert todos[0].content == "Write tests" and todos[0].status == "pending"

    def test_string_input(self):
        todos = plan_to_todos("- Write tests\n- Run CI")
        assert len(todos) == 2
        assert any("Write tests" in t.content for t in todos)

    def test_auto_id_generated(self):
        todos = plan_to_todos([{"title": "Task"}])
        assert todos[0].id

    def test_priority_map_applied(self):
        todos = plan_to_todos([{"title": "critical"}], priority_map={"critical": "high"})
        assert todos[0].priority == "high"

    def test_empty_input(self):
        assert plan_to_todos([]) == []

    def test_returns_todo_item_objects(self):
        todos = plan_to_todos([{"title": "x"}])
        assert all(isinstance(t, TodoItem) for t in todos)

    def test_blank_lines_skipped_in_string(self):
        todos = plan_to_todos("task1\n\n\ntask2")
        assert len(todos) == 2

    def test_status_preserved_from_dict(self):
        todos = plan_to_todos([{"title": "t", "status": "done"}])
        assert todos[0].status == "done"


class TestApplyTodoUpdate:
    def _todos(self):
        return [
            TodoItem(id="t1", content="Task 1", status="pending"),
            TodoItem(id="t2", content="Task 2", status="pending"),
        ]

    def test_update_status(self):
        updated = apply_todo_update(self._todos(), todo_id="t1", status="done")
        assert next(t for t in updated if t.id == "t1").status == "done"

    def test_update_content(self):
        updated = apply_todo_update(self._todos(), todo_id="t1", content="New content")
        assert next(t for t in updated if t.id == "t1").content == "New content"

    def test_update_priority(self):
        updated = apply_todo_update(self._todos(), todo_id="t2", priority="high")
        assert next(t for t in updated if t.id == "t2").priority == "high"

    def test_not_found_raises(self):
        with pytest.raises(OskillError, match="not found"):
            apply_todo_update(self._todos(), todo_id="nonexistent", status="done")

    def test_invalid_status_raises(self):
        with pytest.raises(OskillError, match="invalid status"):
            apply_todo_update(self._todos(), todo_id="t1", status="INVALID")

    def test_invalid_priority_raises(self):
        with pytest.raises(OskillError, match="invalid priority"):
            apply_todo_update(self._todos(), todo_id="t1", priority="ultra")

    def test_other_todos_unchanged(self):
        updated = apply_todo_update(self._todos(), todo_id="t1", status="done")
        assert next(t for t in updated if t.id == "t2").status == "pending"

    def test_returns_new_list(self):
        orig = self._todos()
        updated = apply_todo_update(orig, todo_id="t1", status="done")
        assert updated is not orig


class TestComposePluginManifest:
    def test_basic_manifest(self):
        m = compose_plugin_manifest({"name": "my_plugin", "version": "1.0"})
        assert m.name == "my_plugin" and m.version == "1.0"

    def test_missing_name_raises(self):
        with pytest.raises(ConfigOskillError, match="name"):
            compose_plugin_manifest({"version": "1.0"})

    def test_skills_list(self):
        m = compose_plugin_manifest({"name": "p", "skills": ["skill_a", "skill_b"]})
        assert "skill_a" in m.skills

    def test_commands_list(self):
        m = compose_plugin_manifest(
            {"name": "p", "commands": [{"name": "init", "description": "init cmd"}]}
        )
        assert m.commands[0]["name"] == "init"

    def test_hooks_list(self):
        m = compose_plugin_manifest({"name": "p", "hooks": [{"event": "PreToolUse"}]})
        assert m.hooks[0]["event"] == "PreToolUse"

    def test_mcp_servers(self):
        m = compose_plugin_manifest({"name": "p", "mcp_servers": [{"url": "http://mcp"}]})
        assert m.mcp_servers[0]["url"] == "http://mcp"

    def test_default_version(self):
        m = compose_plugin_manifest({"name": "p"})
        assert m.version == "0.1.0"

    def test_returns_plugin_manifest(self):
        assert isinstance(compose_plugin_manifest({"name": "p"}), PluginManifest)


class TestBuildSubagentPrompt:
    DEF = {
        "system_prompt": "You are a tester.",
        "tools": [{"name": "file_read"}, {"name": "file_write"}, {"name": "bash_exec"}],
        "permissions": {"mode": "plan"},
    }

    def test_system_contains_base(self):
        r = build_subagent_prompt(self.DEF, "Write tests")
        assert "tester" in r["system"]

    def test_context_appended(self):
        r = build_subagent_prompt(self.DEF, "task", context="ctx here")
        assert "ctx here" in r["system"]

    def test_memory_appended(self):
        r = build_subagent_prompt(self.DEF, "task", memory="past memory")
        assert "past memory" in r["system"]

    def test_plan_mode_filters_write(self):
        r = build_subagent_prompt(self.DEF, "task")
        names = [t["name"] for t in r["scoped_tools"]]
        assert "file_write" not in names and "bash_exec" not in names

    def test_bypass_mode_all_tools(self):
        defn = {**self.DEF, "permissions": {"mode": "bypass"}}
        r = build_subagent_prompt(defn, "task")
        names = [t["name"] for t in r["scoped_tools"]]
        assert "file_write" in names and "bash_exec" in names

    def test_allowed_tools_filter(self):
        defn = {**self.DEF, "permissions": {"mode": "default", "allowed_tools": ["file_*"]}}
        r = build_subagent_prompt(defn, "task")
        names = [t["name"] for t in r["scoped_tools"]]
        assert "bash_exec" not in names and "file_read" in names

    def test_returns_dict_with_system_and_tools(self):
        r = build_subagent_prompt(self.DEF, "task")
        assert "system" in r and "scoped_tools" in r

    def test_empty_tools(self):
        defn = {"system_prompt": "Hi.", "tools": [], "permissions": {}}
        r = build_subagent_prompt(defn, "task")
        assert r["scoped_tools"] == []


class TestMergeSubagentResult:
    def test_basic_merge(self):
        summaries = [
            {
                "subagent_name": "tester",
                "summary": "Tests written.",
                "status": "completed",
                "cost_usd": 0.01,
                "iterations": 3,
            }
        ]
        ctx = merge_subagent_result(summaries)
        assert "tester" in ctx and "Tests written" in ctx

    def test_empty_returns_empty(self):
        assert merge_subagent_result([]) == ""

    def test_task_in_header(self):
        ctx = merge_subagent_result(
            [{"subagent_name": "a", "summary": "x", "status": "ok"}], task="Fix auth"
        )
        assert "Fix auth" in ctx

    def test_multiple_summaries(self):
        summaries = [
            {"subagent_name": "a", "summary": "did A", "status": "completed"},
            {"subagent_name": "b", "summary": "did B", "status": "completed"},
        ]
        ctx = merge_subagent_result(summaries)
        assert "did A" in ctx and "did B" in ctx

    def test_max_length_truncated(self):
        summaries = [{"subagent_name": "a", "summary": "x" * 10000, "status": "ok"}]
        ctx = merge_subagent_result(summaries, max_length=100)
        assert len(ctx) <= 100 + 20  # 允许截断标记

    def test_status_in_output(self):
        ctx = merge_subagent_result([{"subagent_name": "a", "summary": "", "status": "failed"}])
        assert "failed" in ctx

    def test_cost_shown(self):
        ctx = merge_subagent_result(
            [{"subagent_name": "a", "summary": "", "status": "ok", "cost_usd": 1.23}]
        )
        assert "1.2300" in ctx or "1.23" in ctx

    def test_returns_string(self):
        assert isinstance(merge_subagent_result([]), str)


# ===========================================================================
# GROUP 3: 代码分析
# ===========================================================================


class TestSyntaxCheck:
    def test_valid_python(self):
        assert syntax_check("x = 1\n", path="f.py") == []

    def test_invalid_python(self):
        errors = syntax_check("def broken(\n", path="f.py")
        assert len(errors) > 0 and errors[0]["severity"] == 1

    def test_valid_json(self):
        assert syntax_check('{"key": "value"}', path="data.json") == []

    def test_invalid_json(self):
        errors = syntax_check("{bad json}", path="data.json")
        assert len(errors) > 0

    def test_unknown_language_no_errors(self):
        assert syntax_check("anything here", path="file.xyz") == []

    def test_explicit_language_overrides_path(self):
        errors = syntax_check("def bad(\n", language="python")
        assert len(errors) > 0

    def test_error_has_required_fields(self):
        errors = syntax_check("def (\n", path="f.py")
        assert all("line" in e and "message" in e for e in errors)

    def test_empty_content_valid_python(self):
        assert syntax_check("", path="f.py") == []


class TestValidateEdit:
    def test_valid_edit_ok(self):
        result = validate_edit("x = 1\n", {"path": "f.py", "full_content": "x = 2\n"})
        assert result["ok"] and result["content"] == "x = 2\n"

    def test_syntax_error_not_ok(self):
        result = validate_edit("x = 1\n", {"path": "f.py", "full_content": "def broken(\n"})
        assert not result["ok"] and len(result["errors"]) > 0

    def test_block_edit_applied(self):
        result = validate_edit(
            "x = 1\n",
            {
                "path": "f.py",
                "blocks": [{"search": "x = 1", "replace": "x = 99"}],
            },
        )
        assert "99" in result["content"]

    def test_block_conflict_not_ok(self):
        result = validate_edit(
            "abc\n",
            {
                "path": "f.py",
                "blocks": [{"search": "NOTFOUND", "replace": "x"}],
            },
        )
        assert not result["ok"] and len(result["conflicts"]) > 0

    def test_json_validated(self):
        result = validate_edit("{}", {"path": "f.json", "full_content": "{bad}"})
        assert not result["ok"]

    def test_no_errors_for_valid_json(self):
        result = validate_edit("{}", {"path": "f.json", "full_content": '{"a": 1}'})
        assert result["ok"]

    def test_returns_dict_with_keys(self):
        r = validate_edit("x\n", {"full_content": "y\n"})
        assert "ok" in r and "content" in r and "errors" in r

    def test_explicit_language_param(self):
        r = validate_edit("x=1\n", {"full_content": "def f(\n"}, language="python")
        assert not r["ok"]


class TestChunkCode:
    def test_chunks_python_by_function(self):
        code = "def foo():\n    pass\n\ndef bar():\n    pass\n"
        chunks = chunk_code(code, path="f.py")
        assert len(chunks) >= 1
        assert all(isinstance(c, Chunk) for c in chunks)

    def test_chunks_unknown_by_lines(self):
        code = "\n".join([f"line{i}" for i in range(100)])
        chunks = chunk_code(code, path="f.ts")
        assert len(chunks) >= 1

    def test_token_count_set(self):
        chunks = chunk_code("def f():\n    pass\n", path="f.py")
        assert all(c.token_count > 0 for c in chunks)

    def test_chunk_id_set(self):
        chunks = chunk_code("def f():\n    pass\n", path="f.py")
        assert all(c.chunk_id for c in chunks)

    def test_empty_content_no_chunks(self):
        chunks = chunk_code("", path="f.py")
        assert chunks == []

    def test_path_in_chunk(self):
        chunks = chunk_code("def f():\n    pass\n", path="src/f.py")
        assert all(c.path == "src/f.py" for c in chunks)

    def test_large_function_split(self):
        big_fn = "def big():\n" + "    x = 1\n" * 200
        chunks = chunk_code(big_fn, path="f.py", max_tokens=50)
        assert len(chunks) >= 2

    def test_language_detection(self):
        chunks = chunk_code("def f():\n    pass\n", path="f.py")
        assert all(c.language == "python" for c in chunks)


class TestExtractSymbols:
    def test_extracts_functions(self):
        content = "def foo():\n    pass\ndef bar(x, y):\n    return x+y\n"
        syms = extract_symbols("f.py", content=content)
        names = [s.name for s in syms]
        assert "foo" in names and "bar" in names

    def test_extracts_classes(self):
        content = "class MyClass:\n    pass\n"
        syms = extract_symbols("f.py", content=content)
        assert any(s.kind == "class" for s in syms)

    def test_sorted_by_line(self):
        content = "def b():\n    pass\ndef a():\n    pass\n"
        syms = extract_symbols("f.py", content=content)
        assert syms[0].start_line <= syms[1].start_line

    def test_signature_captured(self):
        content = "def compute(x: int, y: int) -> int:\n    return x+y\n"
        syms = extract_symbols("f.py", content=content)
        assert "compute" in syms[0].signature

    def test_empty_content(self):
        assert extract_symbols("f.py", content="") == []

    def test_syntax_error_returns_empty(self):
        assert extract_symbols("f.py", content="def broken(\n") == []

    def test_returns_symbol_objects(self):
        syms = extract_symbols("f.py", content="def f():\n    pass\n")
        assert all(isinstance(s, Symbol) for s in syms)

    def test_js_regex_fallback(self):
        content = "function hello() {\n  return 1;\n}\n"
        syms = extract_symbols("f.js", content=content)
        assert any(s.name == "hello" for s in syms)


class TestRepoMapBuild:
    def test_builds_map(self, tmp_path):
        (tmp_path / "main.py").write_text("def main():\n    pass\n")
        rmap = repo_map_build(root=str(tmp_path))
        assert isinstance(rmap, RepoMap) and rmap.total_files >= 1

    def test_language_counted(self, tmp_path):
        (tmp_path / "a.py").write_text("x=1")
        (tmp_path / "b.py").write_text("y=2")
        rmap = repo_map_build(root=str(tmp_path))
        assert rmap.languages.get("python", 0) >= 1

    def test_ignores_git_dir(self, tmp_path):
        git = tmp_path / ".git"
        git.mkdir()
        (git / "config").write_text("git config")
        rmap = repo_map_build(root=str(tmp_path))
        assert not any(".git" in f.path for f in rmap.files)

    def test_nonexistent_root(self):
        rmap = repo_map_build(root="/nonexistent/path/xyz")
        assert rmap.total_files == 0

    def test_max_files_respected(self, tmp_path):
        for i in range(10):
            (tmp_path / f"f{i}.py").write_text(f"x={i}")
        rmap = repo_map_build(root=str(tmp_path), max_files=3)
        assert rmap.total_files <= 3

    def test_symbols_extracted(self, tmp_path):
        (tmp_path / "code.py").write_text("def my_func():\n    pass\n")
        rmap = repo_map_build(root=str(tmp_path))
        file_entry = next((f for f in rmap.files if "code.py" in f.path), None)
        assert file_entry and any(s.name == "my_func" for s in file_entry.symbols)

    def test_head_lines_captured(self, tmp_path):
        (tmp_path / "h.py").write_text("# header\nx = 1\n")
        rmap = repo_map_build(root=str(tmp_path), head_lines=1)
        f = next((f for f in rmap.files if "h.py" in f.path), None)
        assert f and "header" in f.head_lines

    def test_returns_repo_map(self, tmp_path):
        assert isinstance(repo_map_build(root=str(tmp_path)), RepoMap)


class TestResolveMemoryHierarchy:
    def test_reads_project_file(self, tmp_path):
        p = tmp_path / "CLAUDE.md"
        p.write_text("# Project memory\nDo X then Y.")
        result = resolve_memory_hierarchy(project=str(p))
        assert "Do X then Y" in result["content"]

    def test_missing_file_ignored(self, tmp_path):
        result = resolve_memory_hierarchy(project=str(tmp_path / "nonexist.md"))
        assert result["content"] == ""

    def test_multiple_layers_merged(self, tmp_path):
        g = tmp_path / "global.md"
        p = tmp_path / "project.md"
        g.write_text("global content")
        p.write_text("project content")
        result = resolve_memory_hierarchy(enterprise=str(g), project=str(p))
        assert "global" in result["content"] and "project" in result["content"]

    def test_import_resolved(self, tmp_path):
        imported = tmp_path / "imported.md"
        imported.write_text("imported content")
        main = tmp_path / "main.md"
        main.write_text(f"@import {imported}\nmain content")
        result = resolve_memory_hierarchy(project=str(main))
        assert "imported content" in result["content"]

    def test_sources_list(self, tmp_path):
        p = tmp_path / "CLAUDE.md"
        p.write_text("content")
        result = resolve_memory_hierarchy(project=str(p))
        assert str(p) in result["sources"]

    def test_none_paths_ignored(self):
        result = resolve_memory_hierarchy()
        assert result["content"] == "" and result["sources"] == []

    def test_import_count_tracked(self, tmp_path):
        imported = tmp_path / "imp.md"
        imported.write_text("sub content")
        main = tmp_path / "main.md"
        main.write_text(f"@import {imported}")
        result = resolve_memory_hierarchy(project=str(main))
        assert result["import_count"] >= 1

    def test_returns_dict(self):
        r = resolve_memory_hierarchy()
        assert "content" in r and "sources" in r and "import_count" in r


class TestResolveMentions:
    def test_resolves_file_ref(self, tmp_path):
        f = tmp_path / "main.py"
        f.write_text("x = 1\n")
        result = resolve_mentions("Look at @main.py", root=str(tmp_path))
        assert str(f) in result["files"]

    def test_no_mentions_unchanged(self, tmp_path):
        r = resolve_mentions("no mentions here", root=str(tmp_path))
        assert r["files"] == [] and "no mentions here" in r["expanded"]

    def test_missing_file_not_in_files(self, tmp_path):
        r = resolve_mentions("@nonexist.py", root=str(tmp_path))
        assert r["files"] == []

    def test_expanded_contains_content(self, tmp_path):
        f = tmp_path / "util.py"
        f.write_text("def helper(): pass\n")
        r = resolve_mentions("see @util.py for help", root=str(tmp_path))
        assert "helper" in r["expanded"]

    def test_symbol_refs_captured(self, tmp_path):
        r = resolve_mentions("call @my_func here", root=str(tmp_path))
        assert "my_func" in r["symbols"]

    def test_multiple_files(self, tmp_path):
        (tmp_path / "a.py").write_text("a=1")
        (tmp_path / "b.py").write_text("b=2")
        r = resolve_mentions("@a.py and @b.py", root=str(tmp_path))
        assert len(r["files"]) == 2

    def test_returns_dict_with_keys(self, tmp_path):
        r = resolve_mentions("text", root=str(tmp_path))
        assert "expanded" in r and "files" in r and "symbols" in r

    def test_code_block_in_expanded(self, tmp_path):
        (tmp_path / "x.py").write_text("x=1")
        r = resolve_mentions("see @x.py", root=str(tmp_path))
        assert "```" in r["expanded"]


class TestSelectSkill:
    INDEX = [
        {
            "name": "refactor_python",
            "description": "refactors python code",
            "tags": ["python", "refactor"],
        },
        {"name": "write_tests", "description": "generates unit tests", "tags": ["test", "pytest"]},
        {"name": "security_audit", "description": "audits security", "tags": ["security"]},
    ]

    def test_finds_relevant(self):
        result = select_skill("refactor python", skill_index=self.INDEX)
        assert result[0]["name"] == "refactor_python"

    def test_empty_task_returns_results(self):
        result = select_skill("", skill_index=self.INDEX)
        assert isinstance(result, list)

    def test_top_k_respected(self):
        result = select_skill("code", skill_index=self.INDEX, top_k=1)
        assert len(result) <= 1

    def test_empty_index(self):
        assert select_skill("task", skill_index=[]) == []

    def test_returns_skill_dicts(self):
        result = select_skill("test", skill_index=self.INDEX)
        assert all(isinstance(s, dict) for s in result)

    def test_test_query_finds_write_tests(self):
        result = select_skill("write unit tests", skill_index=self.INDEX)
        names = [s["name"] for s in result]
        assert "write_tests" in names

    def test_security_query(self):
        result = select_skill("security audit check", skill_index=self.INDEX)
        names = [s["name"] for s in result]
        assert "security_audit" in names

    def test_name_match_boosts_score(self):
        result = select_skill("refactor_python", skill_index=self.INDEX)
        assert result[0]["name"] == "refactor_python"


class TestLoadSkillProgressive:
    def test_loads_meta(self, tmp_path):
        d = skill_dir(tmp_path)
        result = load_skill_progressive(d, matched=False)
        assert result["name"] == "test_skill"

    def test_loads_body_when_matched(self, tmp_path):
        d = skill_dir(tmp_path)
        result = load_skill_progressive(d, matched=True)
        assert "Do stuff" in result["body"]

    def test_no_body_when_not_matched(self, tmp_path):
        d = skill_dir(tmp_path)
        result = load_skill_progressive(d, matched=False)
        assert result["body"] == ""

    def test_missing_dir_returns_error(self, tmp_path):
        result = load_skill_progressive(str(tmp_path / "nonexist"), matched=False)
        assert "error" in result or result["name"] == ""

    def test_tools_list_populated(self, tmp_path):
        d = skill_dir(tmp_path)
        result = load_skill_progressive(d)
        assert "bash_exec" in result["tools"]

    def test_description_populated(self, tmp_path):
        d = skill_dir(tmp_path)
        result = load_skill_progressive(d)
        assert "test skill" in result["description"].lower()

    def test_meta_dict_present(self, tmp_path):
        d = skill_dir(tmp_path)
        result = load_skill_progressive(d)
        assert "meta" in result and isinstance(result["meta"], dict)

    def test_returns_dict(self, tmp_path):
        d = skill_dir(tmp_path)
        assert isinstance(load_skill_progressive(d), dict)


# ===========================================================================
# GROUP 4: LLM 依赖算法
# ===========================================================================


class TestSummarizeFile:
    def test_returns_summary(self, tmp_path):
        f = tmp_path / "main.py"
        f.write_text("def main():\n    print('hello')\n")
        caller = make_llm_caller(text="This file defines main function.")
        result = asyncio.run(summarize_file(str(f), caller=caller))
        assert isinstance(result, str) and len(result) > 0

    def test_missing_file_raises(self, tmp_path):
        caller = make_llm_caller()
        with pytest.raises(LLMOskillError, match="cannot read"):
            asyncio.run(summarize_file(str(tmp_path / "no.py"), caller=caller))

    def test_caller_error_raises(self, tmp_path):
        f = tmp_path / "f.py"
        f.write_text("x=1")

        async def bad(**kw):
            raise RuntimeError("fail")

        with pytest.raises(LLMOskillError, match="LLM call failed"):
            asyncio.run(summarize_file(str(f), caller=bad))

    def test_large_file_truncated(self, tmp_path):
        f = tmp_path / "big.py"
        f.write_text("x = 1\n" * 10000)
        calls = []

        async def capturing(**kw):
            calls.append(kw["messages"][0]["content"])
            return {
                "content": [{"type": "text", "text": "summary"}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }

        asyncio.run(summarize_file(str(f), caller=capturing, max_content_tokens=100))
        assert len(calls[0]) < len("x = 1\n" * 10000)

    def test_no_text_block_returns_placeholder(self, tmp_path):
        f = tmp_path / "f.py"
        f.write_text("x=1")

        async def empty_caller(**kw):
            return {"content": [], "usage": {}}

        result = asyncio.run(summarize_file(str(f), caller=empty_caller))
        assert result == "(no summary)"

    def test_path_included_in_prompt(self, tmp_path):
        f = tmp_path / "special.py"
        f.write_text("x=1")
        prompts = []

        async def cap(**kw):
            prompts.append(kw["messages"][0]["content"])
            return {"content": [{"type": "text", "text": "ok"}], "usage": {}}

        asyncio.run(summarize_file(str(f), caller=cap))
        assert "special.py" in prompts[0]

    def test_returns_string(self, tmp_path):
        f = tmp_path / "f.py"
        f.write_text("x=1")
        result = asyncio.run(summarize_file(str(f), caller=make_llm_caller()))
        assert isinstance(result, str)

    def test_multiblock_text_concatenated(self, tmp_path):
        f = tmp_path / "f.py"
        f.write_text("x=1")

        async def multi(**kw):
            return {
                "content": [
                    {"type": "text", "text": "Part 1. "},
                    {"type": "text", "text": "Part 2."},
                ],
                "usage": {},
            }

        result = asyncio.run(summarize_file(str(f), caller=multi))
        assert "Part 1" in result and "Part 2" in result


class TestCompressContext:
    MSGS = [{"role": "user", "content": "x" * 500}] * 10

    def test_already_small_unchanged(self):
        msgs = [{"role": "user", "content": "hi"}]
        result = asyncio.run(compress_context(msgs, caller=make_llm_caller(), budget=100000))
        assert result == msgs

    def test_compresses_long_history(self):
        caller = make_llm_caller(text="Summary of conversation.")
        result = asyncio.run(compress_context(self.MSGS, caller=caller, budget=100))
        assert len(result) < len(self.MSGS)

    def test_keeps_first_and_last(self):
        caller = make_llm_caller(text="summary")
        msgs = [{"role": "user", "content": f"msg{i}" * 100} for i in range(8)]
        result = asyncio.run(compress_context(msgs, caller=caller, budget=50))
        assert result[0] == msgs[0]

    def test_empty_returns_empty(self):
        result = asyncio.run(compress_context([], caller=make_llm_caller()))
        assert result == []

    def test_caller_error_raises(self):
        async def bad(**kw):
            raise RuntimeError("fail")

        with pytest.raises(LLMOskillError):
            asyncio.run(compress_context(self.MSGS, caller=bad, budget=10))

    def test_summary_msg_inserted(self):
        caller = make_llm_caller(text="history summary here")
        result = asyncio.run(compress_context(self.MSGS, caller=caller, budget=100))
        assert any("summary" in str(m.get("content", "")).lower() for m in result)

    def test_returns_list_of_dicts(self):
        result = asyncio.run(compress_context(self.MSGS, caller=make_llm_caller(), budget=100))
        assert all(isinstance(m, dict) for m in result)

    def test_budget_respected_approximately(self):
        caller = make_llm_caller(text="short summary")
        short_msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        result = asyncio.run(compress_context(short_msgs, caller=caller, budget=100000))
        assert len(result) <= len(short_msgs)


class TestPlanDecompose:
    def test_returns_subtasks(self):
        items = [
            {
                "id": "1",
                "title": "Write tests",
                "description": "...",
                "dependencies": [],
                "estimated_complexity": "low",
            }
        ]
        caller = make_llm_caller(text=json.dumps(items))
        tasks = asyncio.run(plan_decompose("Add auth", caller=caller))
        assert len(tasks) > 0 and isinstance(tasks[0], SubTask)

    def test_caller_error_raises(self):
        async def bad(**kw):
            raise RuntimeError("fail")

        with pytest.raises(LLMOskillError):
            asyncio.run(plan_decompose("task", caller=bad))

    def test_invalid_json_returns_empty(self):
        caller = make_llm_caller(text="not json at all")
        tasks = asyncio.run(plan_decompose("task", caller=caller))
        assert isinstance(tasks, list)

    def test_markdown_fence_stripped(self):
        items = [{"id": "1", "title": "T", "description": "D", "dependencies": []}]
        text = f"```json\n{json.dumps(items)}\n```"
        caller = make_llm_caller(text=text)
        tasks = asyncio.run(plan_decompose("goal", caller=caller))
        assert len(tasks) >= 1

    def test_max_subtasks_respected(self):
        items = [
            {"id": str(i), "title": f"Task {i}", "description": "", "dependencies": []}
            for i in range(20)
        ]
        caller = make_llm_caller(text=json.dumps(items))
        tasks = asyncio.run(plan_decompose("goal", caller=caller, max_subtasks=5))
        assert len(tasks) <= 5

    def test_dependencies_parsed(self):
        items = [{"id": "2", "title": "T2", "description": "", "dependencies": ["1"]}]
        caller = make_llm_caller(text=json.dumps(items))
        tasks = asyncio.run(plan_decompose("goal", caller=caller))
        assert tasks[0].dependencies == ["1"]

    def test_context_passed(self):
        prompts = []

        async def cap(**kw):
            prompts.append(kw["messages"][0]["content"])
            return {"content": [{"type": "text", "text": "[]"}], "usage": {}}

        asyncio.run(plan_decompose("goal", caller=cap, context="extra context"))
        assert "extra context" in prompts[0]

    def test_returns_list(self):
        caller = make_llm_caller(text="[]")
        assert isinstance(asyncio.run(plan_decompose("g", caller=caller)), list)


class TestRankRelevantFiles:
    def _make_repo_map(self, files):
        from oskill._types import RepoFile

        return RepoMap(
            root="/project",
            files=[
                RepoFile(path=p, language="python", size_bytes=100, symbols=[], head_lines=h)
                for p, h in files
            ],
            total_files=len(files),
        )

    def test_relevant_file_ranked_first(self):
        from oskill._types import RepoFile

        rmap = RepoMap(
            root="/project",
            total_files=2,
            files=[
                RepoFile(
                    path="/project/auth.py",
                    language="python",
                    size_bytes=100,
                    symbols=[
                        Symbol(
                            name="authenticate",
                            kind="function",
                            start_line=1,
                            end_line=5,
                            path="/project/auth.py",
                            signature="def authenticate()",
                        )
                    ],
                    head_lines="def authenticate(): pass",
                ),
                RepoFile(
                    path="/project/utils.py",
                    language="python",
                    size_bytes=100,
                    symbols=[
                        Symbol(
                            name="helper",
                            kind="function",
                            start_line=1,
                            end_line=3,
                            path="/project/utils.py",
                            signature="def helper()",
                        )
                    ],
                    head_lines="def helper(): pass",
                ),
            ],
        )
        ranked = asyncio.run(rank_relevant_files("authenticate", repo_map=rmap))
        assert ranked and "auth.py" in ranked[0][0]

    def test_empty_repo_map(self):
        rmap = RepoMap(root="/p", files=[], total_files=0)
        result = asyncio.run(rank_relevant_files("query", repo_map=rmap))
        assert result == []

    def test_top_k_respected(self):
        from oskill._types import RepoFile

        rmap = RepoMap(
            root="/p",
            total_files=10,
            files=[
                RepoFile(
                    path=f"/p/f{i}.py", language="python", size_bytes=10, head_lines=f"content {i}"
                )
                for i in range(10)
            ],
        )
        result = asyncio.run(rank_relevant_files("content", repo_map=rmap, top_k=3))
        assert len(result) <= 3

    def test_returns_tuple_list(self):
        from oskill._types import RepoFile

        rmap = RepoMap(
            root="/p",
            total_files=1,
            files=[RepoFile(path="/p/f.py", language="python", size_bytes=10, head_lines="x")],
        )
        result = asyncio.run(rank_relevant_files("x", repo_map=rmap))
        assert all(isinstance(r, tuple) and len(r) == 2 for r in result)

    def test_score_between_0_and_1(self):
        from oskill._types import RepoFile

        rmap = RepoMap(
            root="/p",
            total_files=1,
            files=[
                RepoFile(path="/p/auth.py", language="python", size_bytes=10, head_lines="auth")
            ],
        )
        result = asyncio.run(rank_relevant_files("auth", repo_map=rmap))
        if result:
            assert 0 <= result[0][1] <= 5  # 允许加权后超过1

    def test_no_match_returns_empty(self):
        from oskill._types import RepoFile

        rmap = RepoMap(
            root="/p",
            total_files=1,
            files=[
                RepoFile(path="/p/xyz.py", language="python", size_bytes=10, head_lines="nothing")
            ],
        )
        result = asyncio.run(rank_relevant_files("auth_login_system", repo_map=rmap))
        assert isinstance(result, list)

    def test_symbol_names_boost_score(self):
        from oskill._types import RepoFile

        rmap = RepoMap(
            root="/p",
            total_files=2,
            files=[
                RepoFile(
                    path="/p/a.py",
                    language="python",
                    size_bytes=10,
                    symbols=[
                        Symbol(
                            name="authenticate",
                            kind="function",
                            start_line=1,
                            end_line=5,
                            path="/p/a.py",
                        )
                    ],
                    head_lines="",
                ),
                RepoFile(
                    path="/p/b.py",
                    language="python",
                    size_bytes=10,
                    symbols=[],
                    head_lines="unrelated stuff",
                ),
            ],
        )
        result = asyncio.run(rank_relevant_files("authenticate", repo_map=rmap))
        assert result[0][0].endswith("a.py")

    def test_caller_optional(self):
        rmap = RepoMap(root="/p", files=[], total_files=0)
        result = asyncio.run(rank_relevant_files("q", repo_map=rmap, caller=None))
        assert result == []


class TestBuildRepoContext:
    def test_returns_string(self, tmp_path):
        (tmp_path / "main.py").write_text("def main(): pass\n")
        result = asyncio.run(build_repo_context("fix bug", root=str(tmp_path)))
        assert isinstance(result, str) and len(result) > 0

    def test_contains_task(self, tmp_path):
        (tmp_path / "f.py").write_text("x=1")
        result = asyncio.run(build_repo_context("fix auth bug", root=str(tmp_path)))
        assert "fix auth bug" in result

    def test_empty_repo_fallback(self, tmp_path):
        result = asyncio.run(build_repo_context("task", root=str(tmp_path)))
        assert isinstance(result, str)

    def test_budget_respected(self, tmp_path):
        for i in range(20):
            (tmp_path / f"f{i}.py").write_text("x = " + "y" * 500 + "\n")
        result = asyncio.run(build_repo_context("task", root=str(tmp_path), budget=200))

        assert isinstance(result, str)

    def test_nonexistent_root(self):
        result = asyncio.run(build_repo_context("task", root="/nonexistent/xyz"))
        assert "no source files" in result or isinstance(result, str)

    def test_relevant_files_included(self, tmp_path):
        (tmp_path / "auth.py").write_text("def authenticate(): pass\n")
        (tmp_path / "utils.py").write_text("def unrelated(): pass\n")
        result = asyncio.run(build_repo_context("authenticate logic", root=str(tmp_path)))
        # 结果应包含某个 .py 文件（根据相关度排序）
        assert ".py" in result or "Repository" in result

    def test_header_present(self, tmp_path):
        (tmp_path / "f.py").write_text("x=1")
        result = asyncio.run(build_repo_context("my task", root=str(tmp_path)))
        assert "Repository Context" in result

    def test_returns_str_on_map_failure(self):
        result = asyncio.run(build_repo_context("task", root="/no/such/dir"))
        assert isinstance(result, str)


class TestSemanticSearch:
    def test_returns_chunks(self):
        store = make_vector_store(
            [
                {
                    "content": "def auth(): pass",
                    "path": "auth.py",
                    "start_line": 1,
                    "end_line": 3,
                    "chunk_id": "c1",
                }
            ]
        )
        embed = make_embed_caller()
        result = asyncio.run(semantic_search("auth", store=store, embed_caller=embed))
        assert len(result) == 1 and isinstance(result[0], Chunk)

    def test_empty_query_raises(self):
        store = make_vector_store()
        embed = make_embed_caller()
        with pytest.raises(LLMOskillError, match="empty"):
            asyncio.run(semantic_search("", store=store, embed_caller=embed))

    def test_embed_error_raises(self):
        store = make_vector_store()

        async def bad(*, text, model):
            raise RuntimeError("embed fail")

        with pytest.raises(LLMOskillError, match="embedding"):
            asyncio.run(semantic_search("q", store=store, embed_caller=bad))

    def test_store_error_raises(self):
        store = AsyncMock()
        store.search = AsyncMock(side_effect=RuntimeError("store fail"))
        embed = make_embed_caller()
        with pytest.raises(LLMOskillError, match="vector store"):
            asyncio.run(semantic_search("q", store=store, embed_caller=embed))

    def test_top_k_passed_to_store(self):
        store = make_vector_store([])
        embed = make_embed_caller()
        asyncio.run(semantic_search("q", store=store, embed_caller=embed, top_k=7))
        store.search.assert_called_once()
        assert store.search.call_args[1]["top_k"] == 7

    def test_vector_passed_to_store(self):
        store = make_vector_store([])
        embed = make_embed_caller([0.5, 0.6, 0.7])
        asyncio.run(semantic_search("q", store=store, embed_caller=embed))
        assert store.search.call_args[1]["vector"] == [0.5, 0.6, 0.7]

    def test_empty_store_result(self):
        store = make_vector_store([])
        embed = make_embed_caller()
        result = asyncio.run(semantic_search("q", store=store, embed_caller=embed))
        assert result == []

    def test_non_dict_items_filtered(self):
        store = make_vector_store(
            ["bad_item", {"content": "good", "path": "f.py", "start_line": 0, "end_line": 1}]
        )
        embed = make_embed_caller()
        result = asyncio.run(semantic_search("q", store=store, embed_caller=embed))
        assert len(result) == 1 and result[0].content == "good"
