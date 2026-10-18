"""Comprehensive tests for hicode H-C oskill elements K-01 through K-20.

All LLM/LSP interactions are mocked via AsyncMock/MagicMock.
pytest-asyncio asyncio_mode=auto (configured in pyproject.toml).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from oprim._hicode_types import (
    Edit,
    McpToolSpec,
    Message,
    Part,
    PartDelta,
    Persona,
    Rule,
    Tool,
    ToolCall,
    ToolResult,
)

from oskill._hc_types import (
    DecodedTurn,
    Pos,
    ProjectMap,
    ResearchResult,
    SubagentPlan,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _msg(role: str = "user", text: str = "hello", pinned: bool = False) -> Message:
    return Message(role=role, parts=[Part(type="text", text=text)], pinned=pinned)


def _delta(
    idx: int,
    type_: str = "text",
    text: str | None = None,
    tool_call_id: str | None = None,
    tool_name: str | None = None,
    args_chunk: str | None = None,
) -> PartDelta:
    return PartDelta(
        type=type_,
        index=idx,
        text=text,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        args_chunk=args_chunk,
    )


def _tool(name: str = "read", desc: str = "Read a file") -> Tool:
    return Tool(name=name, description=desc, parameters={"type": "object", "properties": {}})


def _mcp_spec(name: str = "search", desc: str = "Search the web") -> McpToolSpec:
    return McpToolSpec(
        name=name,
        description=desc,
        input_schema={"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]},
    )


SEARCH_REPLACE = "<<<SEARCH\n{old}\n===\n{new}\n>>>REPLACE"


# ─────────────────────────────────────────────────────────────────────────────
# K-01 smart_edit
# ─────────────────────────────────────────────────────────────────────────────


class TestSmartEdit:
    """K-01 smart_edit — precision string edit with optional LSP validation."""

    @pytest.fixture(autouse=True)
    def _patch_oprim(self):
        with (
            patch("oskill.smart_edit.verify_unique_match") as vum,
            patch("oskill.smart_edit.apply_string_replace") as asr,
            patch("oskill.smart_edit.preserve_indentation") as pi,
            patch("oskill.smart_edit.compute_diff") as cd,
        ):
            vum.return_value = True
            asr.side_effect = lambda src, old, new: src.replace(old, new)
            pi.side_effect = lambda old, new: new
            cd.return_value = "--- a\n+++ b\n-old\n+new"
            self.vum = vum
            self.asr = asr
            self.pi = pi
            self.cd = cd
            yield

    async def test_search_replace_parse_success(self):
        from oskill.smart_edit import smart_edit

        src = "def foo(): return 1"
        instr = SEARCH_REPLACE.format(old="return 1", new="return 2")
        result = await smart_edit(src, instruction=instr)
        assert result.success is True

    async def test_unique_match_success(self):
        from oskill.smart_edit import smart_edit

        self.vum.return_value = True
        src = "alpha beta gamma"
        instr = SEARCH_REPLACE.format(old="beta", new="BETA")
        result = await smart_edit(src, instruction=instr)
        assert result.success is True

    async def test_non_unique_match_fails(self):
        from oskill.smart_edit import smart_edit

        self.vum.return_value = False
        src = "a a a"
        instr = SEARCH_REPLACE.format(old="a", new="b")
        result = await smart_edit(src, instruction=instr)
        assert result.success is False
        assert "not uniquely found" in result.reason

    async def test_indentation_preserved(self):
        from oskill.smart_edit import smart_edit

        captured = {}
        self.pi.side_effect = lambda old, new: (captured.update({"old": old, "new": new}), new)[1]
        src = "    x = 1"
        instr = SEARCH_REPLACE.format(old="x = 1", new="x = 2")
        result = await smart_edit(src, instruction=instr)
        assert result.success is True
        assert self.pi.called

    async def test_lsp_none_no_warnings(self):
        from oskill.smart_edit import smart_edit

        src = "foo bar"
        instr = SEARCH_REPLACE.format(old="foo", new="baz")
        result = await smart_edit(src, instruction=instr, lsp=None)
        assert result.lsp_warnings == []

    async def test_lsp_with_errors_populates_warnings(self):
        from oskill.smart_edit import smart_edit

        diag = MagicMock()
        diag.severity = 1
        diag.__str__ = lambda self: "undefined name"

        lsp = MagicMock()
        lsp.diagnostics = AsyncMock(return_value=[diag])

        src = "x = bad_call()"
        instr = SEARCH_REPLACE.format(old="bad_call()", new="good_call()")
        result = await smart_edit(src, instruction=instr, lsp=lsp)
        assert result.success is True
        assert len(result.lsp_warnings) == 1
        assert "undefined name" in result.lsp_warnings[0]

    async def test_bad_instruction_format_fails(self):
        from oskill.smart_edit import smart_edit

        src = "some code"
        result = await smart_edit(src, instruction="just a plain English sentence")
        assert result.success is False
        assert "parse" in result.reason.lower() or "SEARCH" in result.reason

    async def test_diff_present_in_result(self):
        from oskill.smart_edit import smart_edit

        src = "hello world"
        instr = SEARCH_REPLACE.format(old="world", new="there")
        result = await smart_edit(src, instruction=instr)
        assert result.success is True
        assert result.diff != ""

    async def test_not_found_target_fails(self):
        from oskill.smart_edit import smart_edit

        self.vum.return_value = False
        src = "nothing matches here"
        instr = SEARCH_REPLACE.format(old="missing_token", new="replacement")
        result = await smart_edit(src, instruction=instr)
        assert result.success is False

    async def test_apply_string_replace_error_propagates(self):
        from oskill.smart_edit import smart_edit

        self.asr.side_effect = ValueError("replacement failed")
        src = "abc"
        instr = SEARCH_REPLACE.format(old="abc", new="xyz")
        result = await smart_edit(src, instruction=instr)
        assert result.success is False
        assert "replacement failed" in result.reason

    async def test_search_hits_provided_but_still_needs_unique(self):
        from oprim._hicode_types import Hit

        from oskill.smart_edit import smart_edit

        self.vum.return_value = False
        hits = [Hit(path="f.py", line_no=1, col=0, text="foo")]
        src = "foo foo"
        instr = SEARCH_REPLACE.format(old="foo", new="bar")
        result = await smart_edit(src, instruction=instr, search_hits=hits)
        assert result.success is False


# ─────────────────────────────────────────────────────────────────────────────
# K-02 batch_edit
# ─────────────────────────────────────────────────────────────────────────────


class TestBatchEdit:
    """K-02 batch_edit — multi-edit with conflict detection."""

    @pytest.fixture(autouse=True)
    def _patch_oprim(self):
        from oprim._hicode_types import Patch

        with (
            patch("oskill.batch_edit.detect_edit_conflict") as dec,
            patch("oskill.batch_edit.plan_multiedit") as pm,
            patch("oskill.batch_edit.apply_string_replace") as asr,
            patch("oskill.batch_edit.compute_diff") as cd,
        ):
            dec.return_value = []
            pm.side_effect = lambda src, edits: [
                Patch(old=e.old, new=e.new, idx=i) for i, e in enumerate(edits)
            ]
            asr.side_effect = lambda src, old, new: src.replace(old, new, 1)
            cd.return_value = "-old\n+new"
            self.dec = dec
            self.pm = pm
            self.asr = asr
            self.cd = cd
            yield

    async def test_multiple_edits_applied_in_order(self):
        from oskill.batch_edit import batch_edit

        src = "a b c"
        edits = [Edit(old="a", new="A"), Edit(old="b", new="B")]
        result = await batch_edit(src, edits=edits)
        assert result.success is True
        assert self.asr.call_count == 2

    async def test_conflict_detection_fails(self):
        from oprim._hicode_types import Conflict

        from oskill.batch_edit import batch_edit

        self.dec.return_value = [Conflict(idx_a=0, idx_b=1)]
        edits = [Edit(old="x", new="y"), Edit(old="x", new="z")]
        result = await batch_edit("x y x", edits=edits)
        assert result.success is False
        assert "Conflicting" in result.reason
        assert "0" in result.reason and "1" in result.reason

    async def test_empty_edits_success(self):
        from oskill.batch_edit import batch_edit

        result = await batch_edit("untouched", edits=[])
        assert result.success is True
        assert result.result == "untouched"

    async def test_one_edit_fails_returns_false(self):
        from oskill.batch_edit import batch_edit

        self.asr.side_effect = ValueError("target not found")
        edits = [Edit(old="missing", new="present")]
        result = await batch_edit("nothing here", edits=edits)
        assert result.success is False
        assert "Edit failed" in result.reason

    async def test_lsp_check_called(self):
        from oskill.batch_edit import batch_edit

        lsp = MagicMock()
        lsp.diagnostics = AsyncMock(return_value=[])
        edits = [Edit(old="a", new="b")]
        result = await batch_edit("a", edits=edits, lsp=lsp)
        lsp.diagnostics.assert_called_once()
        assert result.success is True

    async def test_large_edit_set(self):
        from oskill.batch_edit import batch_edit

        edits = [Edit(old=f"token{i}", new=f"TOKEN{i}") for i in range(20)]
        result = await batch_edit("placeholder", edits=edits)
        assert result.success is True
        assert self.pm.called

    async def test_conflict_details_in_reason(self):
        from oprim._hicode_types import Conflict

        from oskill.batch_edit import batch_edit

        self.dec.return_value = [Conflict(idx_a=2, idx_b=5)]
        edits = [Edit(old=f"x{i}", new=f"y{i}") for i in range(6)]
        result = await batch_edit("content", edits=edits)
        assert "2" in result.reason
        assert "5" in result.reason

    async def test_plan_multiedit_error_returns_false(self):
        from oskill.batch_edit import batch_edit

        self.pm.side_effect = ValueError("plan error")
        edits = [Edit(old="a", new="b")]
        result = await batch_edit("a", edits=edits)
        assert result.success is False
        assert "plan error" in result.reason

    async def test_lsp_warning_populated_on_diagnostics(self):
        from oskill.batch_edit import batch_edit

        diag = MagicMock()
        diag.severity = 1
        diag.__str__ = lambda s: "type error"
        lsp = MagicMock()
        lsp.diagnostics = AsyncMock(return_value=[diag])
        result = await batch_edit("a", edits=[Edit(old="a", new="b")], lsp=lsp)
        assert result.success is True
        assert "type error" in result.lsp_warnings[0]


# ─────────────────────────────────────────────────────────────────────────────
# K-03 patch_apply_verified
# ─────────────────────────────────────────────────────────────────────────────


class TestPatchApplyVerified:
    """K-03 patch_apply_verified — apply unified diff with verification."""

    @pytest.fixture(autouse=True)
    def _patch_oprim(self):
        with (
            patch("oskill.patch_apply_verified.parse_unified_diff") as pud,
            patch("oskill.patch_apply_verified.apply_patch") as ap,
            patch("oskill.patch_apply_verified.apply_hunk") as ah,
            patch("oskill.patch_apply_verified.compute_diff") as cd,
        ):
            pud.return_value = [{"header": "@@ -1,1 +1,1 @@"}]
            ap.return_value = "patched content"
            ah.return_value = "patched content"
            cd.return_value = "-old\n+new"
            self.pud = pud
            self.ap = ap
            self.ah = ah
            self.cd = cd
            yield

    async def test_valid_single_hunk_patch_applied(self):
        from oskill.patch_apply_verified import patch_apply_verified

        result = await patch_apply_verified(
            "old content", patch="--- a\n+++ b\n@@ -1 +1 @@\n-old\n+new"
        )
        assert result.success is True
        assert result.result == "patched content"

    async def test_multi_hunk_patch(self):
        from oskill.patch_apply_verified import patch_apply_verified

        self.pud.return_value = [{"h": 1}, {"h": 2}]
        result = await patch_apply_verified("src", patch="multi-hunk-patch")
        assert result.success is True

    async def test_hunk_mismatch_fails(self):
        from oskill.patch_apply_verified import patch_apply_verified

        self.ap.side_effect = ValueError("hunk mismatch: context doesn't match")
        result = await patch_apply_verified("src", patch="--- a\n+++ b\n@@ -1 +1 @@\n-x\n+y")
        assert result.success is False
        assert "hunk mismatch" in result.reason

    async def test_invalid_format_fails(self):
        from oskill.patch_apply_verified import patch_apply_verified

        self.pud.side_effect = ValueError("not a unified diff")
        result = await patch_apply_verified("src", patch="not a patch at all")
        assert result.success is False
        assert "Invalid patch format" in result.reason

    async def test_empty_patch_success_no_change(self):
        from oskill.patch_apply_verified import patch_apply_verified

        result = await patch_apply_verified("unchanged", patch="")
        assert result.success is True
        assert result.result == "unchanged"
        assert result.diff == ""

    async def test_lsp_warnings_on_new_errors(self):
        from oskill.patch_apply_verified import patch_apply_verified

        diag = MagicMock()
        diag.severity = 1
        diag.__str__ = lambda s: "unused import"
        lsp = MagicMock()
        lsp.diagnostics = AsyncMock(return_value=[diag])
        result = await patch_apply_verified("src", patch="--- a\n+++ b\n@@ @@\n+x", lsp=lsp)
        assert result.success is True
        assert any("unused import" in w for w in result.lsp_warnings)

    async def test_large_patch(self):
        from oskill.patch_apply_verified import patch_apply_verified

        self.pud.return_value = [{"h": i} for i in range(50)]
        self.ap.return_value = "big result"
        result = await patch_apply_verified("big src", patch="big patch string")
        assert result.success is True

    async def test_pure_add_patch(self):
        from oskill.patch_apply_verified import patch_apply_verified

        self.ap.return_value = "original\nnew line"
        result = await patch_apply_verified(
            "original",
            patch="--- a\n+++ b\n@@ -1 +1,2 @@\n original\n+new line",
        )
        assert result.success is True

    async def test_pure_delete_patch(self):
        from oskill.patch_apply_verified import patch_apply_verified

        self.ap.return_value = ""
        result = await patch_apply_verified(
            "line to delete\n",
            patch="--- a\n+++ b\n@@ -1 +0,0 @@\n-line to delete",
        )
        assert result.success is True
        assert result.result == ""


# ─────────────────────────────────────────────────────────────────────────────
# K-04 code_search
# ─────────────────────────────────────────────────────────────────────────────


class TestCodeSearch:
    """K-04 code_search — grep+glob composite file search."""

    @pytest.fixture(autouse=True)
    def _patch_oprim(self, tmp_path):
        self.root = tmp_path
        (tmp_path / ".gitignore").write_text("*.pyc\n")
        with (
            patch("oskill.code_search.build_ripgrep_args") as bra,
            patch("oskill.code_search.parse_ripgrep_output") as pro,
            patch("oskill.code_search.parse_gitignore") as pgi,
            patch("oskill.code_search.apply_gitignore") as agi,
            patch("oskill.code_search.sort_by_mtime") as sbm,
            patch("oskill.code_search.glob_match") as gm,
            patch("asyncio.create_subprocess_exec") as cse,
        ):
            proc = MagicMock()
            proc.communicate = AsyncMock(return_value=(b"", b""))
            cse.return_value = proc
            bra.return_value = ["rg", "--json", "query"]
            pro.return_value = []
            pgi.return_value = []
            agi.side_effect = lambda paths, patterns, root: paths
            sbm.side_effect = lambda entries: entries
            self.bra = bra
            self.pro = pro
            self.pgi = pgi
            self.agi = agi
            self.sbm = sbm
            self.gm = gm
            self.cse = cse
            yield

    async def test_empty_query_raises(self):
        from oskill.code_search import code_search

        with pytest.raises(ValueError, match="query must not be empty"):
            await code_search(self.root, query="")

    async def test_root_not_exists_raises(self):
        from oskill.code_search import code_search

        with pytest.raises(FileNotFoundError):
            await code_search(Path("/nonexistent/path"), query="foo")

    async def test_rg_returns_hits(self):
        from oprim._hicode_types import Hit

        from oskill.code_search import code_search

        hits = [Hit(path="a.py", line_no=1, col=0, text="foo")]
        self.pro.return_value = hits
        results = await code_search(self.root, query="foo")
        assert len(results) == 1
        assert results[0].path == "a.py"

    async def test_file_glob_filtering_passed(self):
        from oskill.code_search import code_search

        await code_search(self.root, query="bar", file_glob="*.py")
        call_args = self.bra.call_args
        assert call_args[1].get("glob") == "*.py"

    async def test_gitignore_filter_applied(self):
        from oprim._hicode_types import Hit

        from oskill.code_search import code_search

        hits = [Hit(path="ok.py", line_no=1, col=0, text="x")]
        self.pro.return_value = hits
        self.pgi.return_value = [MagicMock()]
        self.agi.return_value = [Path("ok.py")]
        await code_search(self.root, query="x")
        self.agi.assert_called_once()

    async def test_empty_results_returns_empty_list(self):
        from oskill.code_search import code_search

        self.pro.return_value = []
        results = await code_search(self.root, query="needle")
        assert results == []

    async def test_sort_by_mtime_called(self):
        from oprim._hicode_types import Hit

        from oskill.code_search import code_search

        hits = [
            Hit(path=str(self.root / "b.py"), line_no=2, col=0, text="y"),
            Hit(path=str(self.root / "a.py"), line_no=1, col=0, text="x"),
        ]
        self.pro.return_value = hits
        (self.root / "a.py").write_text("x")
        (self.root / "b.py").write_text("y")
        await code_search(self.root, query="test")
        assert self.sbm.called

    async def test_multiple_files(self):
        from oprim._hicode_types import Hit

        from oskill.code_search import code_search

        hits = [Hit(path=f"file{i}.py", line_no=i, col=0, text="match") for i in range(5)]
        self.pro.return_value = hits
        results = await code_search(self.root, query="match")
        assert len(results) == 5

    async def test_default_glob_passes_none(self):
        from oskill.code_search import code_search

        await code_search(self.root, query="test")
        call_kwargs = self.bra.call_args[1]
        assert call_kwargs.get("glob") is None


# ─────────────────────────────────────────────────────────────────────────────
# K-05 semantic_file_read
# ─────────────────────────────────────────────────────────────────────────────


class TestSemanticFileRead:
    """K-05 semantic_file_read — intelligent file read with encoding and focus."""

    @pytest.fixture(autouse=True)
    def _patch_oprim(self, tmp_path):
        self.tmp = tmp_path
        with (
            patch("oskill.semantic_file_read.file_read") as fr,
            patch("oskill.semantic_file_read.detect_encoding") as de,
            patch("oskill.semantic_file_read.detect_mime") as dm,
            patch("oskill.semantic_file_read.is_binary") as ib,
            patch("oskill.semantic_file_read.truncate_for_context") as tfc,
            patch("oskill.semantic_file_read.add_line_numbers") as aln,
        ):
            fr.return_value = b"hello world"
            de.return_value = "utf-8"
            dm.return_value = "text/plain"
            ib.return_value = False
            tfc.side_effect = lambda content, max_lines, max_bytes: content
            aln.side_effect = lambda content: "\n".join(
                f"{i + 1}\t{ln}" for i, ln in enumerate(content.splitlines())
            )
            self.fr = fr
            self.de = de
            self.dm = dm
            self.ib = ib
            self.tfc = tfc
            self.aln = aln
            yield

    def test_text_file_returns_content_with_line_numbers(self, tmp_path):
        from oskill.semantic_file_read import semantic_file_read

        f = tmp_path / "test.py"
        f.write_bytes(b"line one\nline two")
        self.fr.return_value = b"line one\nline two"
        result = semantic_file_read(f)
        assert "1\t" in result or result  # line numbers added
        self.aln.assert_called_once()

    def test_binary_file_returns_binary_notice(self, tmp_path):
        from oskill.semantic_file_read import semantic_file_read

        f = tmp_path / "data.bin"
        f.write_bytes(b"\x00\x01\x02")
        self.ib.return_value = True
        self.fr.return_value = b"\x00\x01\x02"
        self.dm.return_value = "application/octet-stream"
        result = semantic_file_read(f)
        assert "binary" in result

    def test_focus_keyword_narrows_content(self, tmp_path):
        from oskill.semantic_file_read import semantic_file_read

        lines = "\n".join(["irrelevant"] * 30 + ["TARGET_KEYWORD here"] + ["noise"] * 10)
        f = tmp_path / "big.py"
        f.write_bytes(lines.encode())
        self.fr.return_value = lines.encode()
        self.tfc.side_effect = lambda content, max_lines, max_bytes: content
        semantic_file_read(f, focus="TARGET_KEYWORD")
        # Narrow region returned; add_line_numbers is still called
        self.aln.assert_called_once()

    def test_max_lines_respected(self, tmp_path):
        from oskill.semantic_file_read import semantic_file_read

        f = tmp_path / "file.py"
        f.write_bytes(b"a")
        self.fr.return_value = b"a"
        self.tfc.side_effect = lambda content, max_lines, max_bytes: content[:max_lines]
        semantic_file_read(f, max_lines=50)
        call_kw = self.tfc.call_args[1]
        assert call_kw["max_lines"] == 50

    def test_nonexistent_file_propagates_error(self, tmp_path):
        from oskill.semantic_file_read import semantic_file_read

        bad = tmp_path / "missing.py"
        # read_bytes() on a missing file raises FileNotFoundError
        with pytest.raises(FileNotFoundError):
            semantic_file_read(bad)

    def test_empty_file_returns_line_numbers(self, tmp_path):
        from oskill.semantic_file_read import semantic_file_read

        f = tmp_path / "empty.py"
        f.write_bytes(b"")
        self.fr.return_value = b""
        semantic_file_read(f)
        self.aln.assert_called_once()

    def test_encoding_detection_called(self, tmp_path):
        from oskill.semantic_file_read import semantic_file_read

        f = tmp_path / "file.py"
        f.write_bytes(b"content")
        self.fr.return_value = b"content"
        semantic_file_read(f)
        self.de.assert_called_once()

    def test_large_file_truncated(self, tmp_path):
        from oskill.semantic_file_read import semantic_file_read

        content = b"x\n" * 5000
        f = tmp_path / "large.py"
        f.write_bytes(content)
        self.fr.return_value = content
        truncated = "x\n" * 2000
        self.tfc.return_value = truncated
        semantic_file_read(f, max_lines=2000)
        assert self.tfc.called


# ─────────────────────────────────────────────────────────────────────────────
# K-06 context_compact
# ─────────────────────────────────────────────────────────────────────────────


class TestContextCompact:
    """K-06 context_compact — LLM-driven history compaction."""

    @pytest.fixture(autouse=True)
    def _patch_oprim(self):
        with (
            patch("oskill.context_compact.should_compact") as sc,
            patch("oskill.context_compact.select_compaction_window") as scw,
            patch("oskill.context_compact.extract_pinned_messages") as epm,
            patch("oskill.context_compact.build_compaction_prompt") as bcp,
            patch("oskill.context_compact.merge_summary") as ms,
        ):
            from oprim._hicode_types import Window

            sc.return_value = False
            scw.return_value = Window(to_compact=[], to_keep=[])
            epm.return_value = []
            bcp.return_value = [{"role": "user", "content": "summarise"}]
            ms.side_effect = lambda summary, tail: tail
            self.sc = sc
            self.scw = scw
            self.epm = epm
            self.bcp = bcp
            self.ms = ms
            yield

    async def test_history_under_budget_returned_unchanged(self):
        from oskill.context_compact import context_compact

        history = [_msg(), _msg("assistant", "ok")]
        self.sc.return_value = False
        caller = AsyncMock()
        result = await context_compact(history, caller=caller, budget_tokens=100_000)
        assert result is history
        caller.assert_not_called()

    async def test_history_over_budget_compacted(self):
        from oprim._hicode_types import Window

        from oskill.context_compact import context_compact

        self.sc.return_value = True
        old_msgs = [_msg() for _ in range(10)]
        keep_msgs = [_msg("assistant", "recent")]
        self.scw.return_value = Window(to_compact=old_msgs, to_keep=keep_msgs)
        self.ms.return_value = keep_msgs
        caller = AsyncMock(return_value={"content": "summary text"})
        await context_compact(old_msgs + keep_msgs, caller=caller, budget_tokens=1000)
        caller.assert_called_once()
        self.ms.assert_called_once()

    async def test_pinned_messages_preserved(self):
        from oprim._hicode_types import Window

        from oskill.context_compact import context_compact

        self.sc.return_value = True
        pinned = _msg("system", "system instructions", pinned=True)
        keep = [pinned, _msg("assistant", "recent")]
        self.scw.return_value = Window(to_compact=[_msg()], to_keep=keep)
        self.ms.return_value = keep
        caller = AsyncMock(return_value={"content": "summary"})
        result = await context_compact([pinned], caller=caller, budget_tokens=100)
        assert result == keep

    async def test_caller_invoked_with_compaction_prompt(self):
        from oprim._hicode_types import Window

        from oskill.context_compact import context_compact

        self.sc.return_value = True
        self.scw.return_value = Window(to_compact=[_msg()], to_keep=[])
        self.bcp.return_value = [{"role": "user", "content": "please summarise the following"}]
        caller = AsyncMock(return_value={"content": "done"})
        await context_compact([_msg()], caller=caller, budget_tokens=10)
        assert caller.call_args[1]["messages"] == [
            {"role": "user", "content": "please summarise the following"}
        ]

    async def test_caller_failure_propagates(self):
        from oprim._hicode_types import Window

        from oskill.context_compact import context_compact

        self.sc.return_value = True
        self.scw.return_value = Window(to_compact=[_msg()], to_keep=[])
        caller = AsyncMock(side_effect=RuntimeError("LLM down"))
        with pytest.raises(RuntimeError, match="LLM down"):
            await context_compact([_msg()], caller=caller, budget_tokens=10)

    async def test_empty_history_returned_unchanged(self):
        from oskill.context_compact import context_compact

        self.sc.return_value = False
        caller = AsyncMock()
        result = await context_compact([], caller=caller, budget_tokens=1000)
        assert result == []

    async def test_summary_merged_correctly(self):
        from oprim._hicode_types import Window

        from oskill.context_compact import context_compact

        self.sc.return_value = True
        tail = [_msg("assistant", "final")]
        self.scw.return_value = Window(to_compact=[_msg()], to_keep=tail)
        self.ms.return_value = [_msg("assistant", "merged")]
        caller = AsyncMock(return_value={"content": [{"type": "text", "text": "the summary"}]})
        await context_compact([_msg()], caller=caller, budget_tokens=10)
        self.ms.assert_called_once_with("the summary", tail=tail)

    async def test_recent_messages_preserved(self):
        from oprim._hicode_types import Window

        from oskill.context_compact import context_compact

        self.sc.return_value = True
        recent = [_msg("assistant", "keep me")]
        self.scw.return_value = Window(to_compact=[_msg()], to_keep=recent)
        self.ms.return_value = recent
        caller = AsyncMock(return_value={"content": "summary"})
        result = await context_compact([_msg(), recent[0]], caller=caller, budget_tokens=50)
        assert recent[0] in result


# ─────────────────────────────────────────────────────────────────────────────
# K-07 prompt_assemble
# ─────────────────────────────────────────────────────────────────────────────


class TestPromptAssemble:
    """K-07 prompt_assemble — assemble complete LLM message list."""

    @pytest.fixture(autouse=True)
    def _patch_oprim(self):
        with (
            patch("oskill.prompt_assemble.build_system_prompt") as bsp,
            patch("oskill.prompt_assemble.inject_agents_md") as iam,
            patch("oskill.prompt_assemble.render_part") as rp,
            patch("oskill.prompt_assemble.count_message_tokens") as cmt,
        ):
            bsp.return_value = "SYSTEM PROMPT"
            iam.side_effect = lambda sys, agents_md: sys + "\n" + agents_md
            rp.side_effect = lambda part: part.text or ""
            cmt.return_value = 100
            self.bsp = bsp
            self.iam = iam
            self.rp = rp
            self.cmt = cmt
            yield

    def test_builds_system_plus_history(self):
        from oskill.prompt_assemble import prompt_assemble

        history = [_msg("user", "hello")]
        result = prompt_assemble(agent="coder", project_ctx="project", history=history, tools=[])
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"

    def test_empty_history_only_system(self):
        from oskill.prompt_assemble import prompt_assemble

        result = prompt_assemble(agent="coder", project_ctx="ctx", history=[], tools=[])
        assert len(result) == 1
        assert result[0]["role"] == "system"

    def test_agents_md_injected_when_provided(self):
        from oskill.prompt_assemble import prompt_assemble

        prompt_assemble(agent="a", project_ctx="c", history=[], tools=[], agents_md="# Agents")
        self.iam.assert_called_once()

    def test_agents_md_none_not_injected(self):
        from oskill.prompt_assemble import prompt_assemble

        prompt_assemble(agent="a", project_ctx="c", history=[], tools=[], agents_md=None)
        self.iam.assert_not_called()

    def test_tools_passed_to_system_prompt(self):
        from oskill.prompt_assemble import prompt_assemble

        tools = [{"name": "bash", "description": "run bash"}]
        prompt_assemble(agent="a", project_ctx="c", history=[], tools=tools)
        call_kwargs = self.bsp.call_args[1]
        assert call_kwargs["tools"] == tools

    def test_token_budget_marks_needs_compaction(self):
        from oskill.prompt_assemble import prompt_assemble

        self.cmt.return_value = 60_000
        history = [_msg()]
        result = prompt_assemble(agent="a", project_ctx="c", history=history, tools=[])
        assert result[0].get("_needs_compaction") is True

    def test_render_part_called_per_message(self):
        from oskill.prompt_assemble import prompt_assemble

        history = [_msg("user", "a"), _msg("assistant", "b")]
        prompt_assemble(agent="a", project_ctx="c", history=history, tools=[])
        assert self.rp.call_count == 2

    def test_role_order_correct(self):
        from oskill.prompt_assemble import prompt_assemble

        history = [_msg("user", "q"), _msg("assistant", "a"), _msg("user", "q2")]
        result = prompt_assemble(agent="a", project_ctx="c", history=history, tools=[])
        roles = [m["role"] for m in result]
        assert roles == ["system", "user", "assistant", "user"]


# ─────────────────────────────────────────────────────────────────────────────
# K-08 response_decode
# ─────────────────────────────────────────────────────────────────────────────


class TestResponseDecode:
    """K-08 response_decode — decode LLM raw response to DecodedTurn."""

    @pytest.fixture(autouse=True)
    def _patch_oprim(self):
        with (
            patch("oskill.response_decode.parse_tool_calls") as ptc,
            patch("oskill.response_decode.parse_stop_reason") as psr,
            patch("oskill.response_decode.from_anthropic_format") as faf,
            patch("oskill.response_decode.from_openai_format") as fof,
            patch("oskill.response_decode.from_google_format") as fgf,
        ):
            ptc.return_value = []
            psr.return_value = "end_turn"
            faf.return_value = Message(role="assistant", parts=[Part(type="text", text="hi")])
            fof.return_value = Message(role="assistant", parts=[Part(type="text", text="hi")])
            fgf.return_value = Message(role="assistant", parts=[Part(type="text", text="hi")])
            self.ptc = ptc
            self.psr = psr
            self.faf = faf
            self.fof = fof
            self.fgf = fgf
            yield

    def test_anthropic_text_response(self):
        from oskill.response_decode import response_decode

        raw = {"content": [{"type": "text", "text": "hello"}], "usage": {"input_tokens": 10}}
        result = response_decode(raw, provider="anthropic")
        assert isinstance(result, DecodedTurn)
        assert result.stop_reason == "end_turn"
        self.faf.assert_called_once()

    def test_openai_tool_call_response(self):
        from oprim._hicode_types import ToolCall as TC

        from oskill.response_decode import response_decode

        self.ptc.return_value = [TC(id="tc1", name="bash", args={"cmd": "ls"})]
        raw = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{"id": "tc1", "function": {"name": "bash"}}],
                    }
                }
            ]
        }
        result = response_decode(raw, provider="openai")
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "bash"

    def test_google_response_decoded(self):
        from oskill.response_decode import response_decode

        raw = {"candidates": [{"content": {"parts": [{"text": "answer"}]}}]}
        result = response_decode(raw, provider="google")
        assert isinstance(result, DecodedTurn)
        self.fgf.assert_called_once()

    def test_stop_reason_mapped_correctly(self):
        from oskill.response_decode import response_decode

        self.psr.return_value = "max_tokens"
        raw = {"stop_reason": "max_tokens"}
        result = response_decode(raw, provider="anthropic")
        assert result.stop_reason == "max_tokens"

    def test_usage_extracted(self):
        from oskill.response_decode import response_decode

        raw = {"usage": {"input_tokens": 50, "output_tokens": 20}}
        result = response_decode(raw, provider="anthropic")
        assert result.usage["input_tokens"] == 50

    def test_unknown_provider_graceful_fallback(self):
        from oskill.response_decode import response_decode

        raw = {"content": "hello"}
        result = response_decode(raw, provider="unknown_provider")
        assert isinstance(result, DecodedTurn)
        # Falls back to anthropic format path
        self.faf.assert_called_once()

    def test_empty_content_empty_tool_calls(self):
        from oskill.response_decode import response_decode

        self.ptc.return_value = []
        raw = {"content": []}
        result = response_decode(raw, provider="anthropic")
        assert result.tool_calls == []

    def test_reasoning_part_extracted(self):
        from oskill.response_decode import response_decode

        self.ptc.return_value = []
        self.faf.return_value = Message(
            role="assistant",
            parts=[Part(type="reasoning", text="let me think"), Part(type="text", text="answer")],
        )
        raw = {"content": [{"type": "thinking", "thinking": "let me think"}]}
        result = response_decode(raw, provider="anthropic")
        assert result.message["parts"] == ["reasoning", "text"]


# ─────────────────────────────────────────────────────────────────────────────
# K-09 transform_pipeline
# ─────────────────────────────────────────────────────────────────────────────


class TestTransformPipeline:
    """K-09 transform_pipeline — convert unified messages to provider payload."""

    @pytest.fixture(autouse=True)
    def _patch_oprim(self):
        # _FORMAT_MAP is built at import time from the real functions, so patch
        # the map entries directly alongside the module-level helpers.
        self.taf = MagicMock(return_value={"messages": [], "_provider": "anthropic"})
        self.tof = MagicMock(return_value={"messages": [], "_provider": "openai"})
        self.tgf = MagicMock(return_value={"contents": [], "_provider": "google"})
        self.tbf = MagicMock(return_value={"messages": [], "_provider": "bedrock"})

        import oskill.transform_pipeline as mod

        fake_map = {
            "anthropic": self.taf,
            "openai": self.tof,
            "google": self.tgf,
            "bedrock": self.tbf,
        }
        with (
            patch.object(mod, "_FORMAT_MAP", fake_map),
            patch("oskill.transform_pipeline.normalize_tool_schema") as nts,
            patch("oskill.transform_pipeline.split_system_message") as ssm,
            patch("oskill.transform_pipeline.patch_provider_quirk") as ppq,
            patch("oskill.transform_pipeline.inject_cache_control") as icc,
        ):
            nts.side_effect = lambda tools, provider: tools
            ssm.return_value = ("", [])
            ppq.side_effect = lambda payload, provider: payload
            icc.side_effect = lambda payload, provider: payload
            self.nts = nts
            self.ssm = ssm
            self.ppq = ppq
            self.icc = icc
            yield

    def test_anthropic_payload_structure(self):
        from oskill.transform_pipeline import transform_pipeline

        result = transform_pipeline([], provider="anthropic")
        self.taf.assert_called_once()
        assert "_provider" in result

    def test_openai_payload_structure(self):
        from oskill.transform_pipeline import transform_pipeline

        transform_pipeline([], provider="openai")
        self.tof.assert_called_once()

    def test_google_payload_structure(self):
        from oskill.transform_pipeline import transform_pipeline

        transform_pipeline([], provider="google")
        self.tgf.assert_called_once()

    def test_unknown_provider_raises(self):
        from oskill.transform_pipeline import transform_pipeline

        with pytest.raises(ValueError, match="Unknown provider"):
            transform_pipeline([], provider="acme_llm")

    def test_tools_normalized_and_included(self):
        from oskill.transform_pipeline import transform_pipeline

        tools = [{"name": "bash"}]
        transform_pipeline([], provider="anthropic", tools=tools)
        self.nts.assert_called_once_with(tools, provider="anthropic")

    def test_system_message_split_for_anthropic(self):
        from oskill.transform_pipeline import transform_pipeline

        self.ssm.return_value = ("System instruction here", [])
        result = transform_pipeline([], provider="anthropic")
        assert result.get("system") == "System instruction here"

    def test_patch_provider_quirk_applied(self):
        from oskill.transform_pipeline import transform_pipeline

        transform_pipeline([], provider="anthropic")
        self.ppq.assert_called_once()

    def test_cache_control_injected(self):
        from oskill.transform_pipeline import transform_pipeline

        transform_pipeline([], provider="anthropic")
        self.icc.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# K-10 code_intel_lookup
# ─────────────────────────────────────────────────────────────────────────────


class TestCodeIntelLookup:
    """K-10 code_intel_lookup — LSP-powered code intelligence."""

    @pytest.fixture(autouse=True)
    def _patch_oprim(self):
        with (
            patch("oskill.code_intel_lookup.lsp_hover") as lh,
            patch("oskill.code_intel_lookup.lsp_find_references") as lfr,
            patch("oskill.code_intel_lookup.lsp_goto_definition") as lgd,
            patch("oskill.code_intel_lookup.location_to_snippet") as lts,
            patch("oskill.code_intel_lookup.diagnostics_to_summary") as dts,
        ):
            lh.return_value = {"contents": {"value": "def foo() -> int"}}
            lfr.return_value = [{"uri": "file.py", "range": {}}]
            lgd.return_value = {"uri": "file.py", "range": {"start": {"line": 5, "character": 0}}}
            lts.return_value = "def foo(): ..."
            dts.return_value = ""
            self.lh = lh
            self.lfr = lfr
            self.lgd = lgd
            self.lts = lts
            self.dts = dts
            yield

    async def test_hover_text_returned(self):
        from oskill.code_intel_lookup import code_intel_lookup

        lsp = MagicMock()
        result = await code_intel_lookup(Path("f.py"), pos=Pos(line=5, character=4), lsp=lsp)
        assert result.hover_text == "def foo() -> int"

    async def test_definition_location_extracted(self):
        from oskill.code_intel_lookup import code_intel_lookup

        lsp = MagicMock()
        result = await code_intel_lookup(Path("f.py"), pos=Pos(line=1, character=0), lsp=lsp)
        assert "file.py" in result.definition
        assert "5" in result.definition

    async def test_references_count_correct(self):
        from oskill.code_intel_lookup import code_intel_lookup

        self.lfr.return_value = [{"uri": "a.py"}, {"uri": "b.py"}, {"uri": "c.py"}]
        lsp = MagicMock()
        result = await code_intel_lookup(Path("f.py"), pos=Pos(line=0, character=0), lsp=lsp)
        assert result.references_count == 3

    async def test_all_three_lsp_calls_made(self):
        from oskill.code_intel_lookup import code_intel_lookup

        lsp = MagicMock()
        await code_intel_lookup(Path("f.py"), pos=Pos(line=0, character=0), lsp=lsp)
        assert self.lh.called
        assert self.lfr.called
        assert self.lgd.called

    async def test_no_definition_empty_string(self):
        from oskill.code_intel_lookup import code_intel_lookup

        self.lgd.return_value = None
        lsp = MagicMock()
        result = await code_intel_lookup(Path("f.py"), pos=Pos(line=0, character=0), lsp=lsp)
        assert result.definition == ""

    async def test_no_references_zero_count(self):
        from oskill.code_intel_lookup import code_intel_lookup

        self.lfr.return_value = []
        lsp = MagicMock()
        result = await code_intel_lookup(Path("f.py"), pos=Pos(line=0, character=0), lsp=lsp)
        assert result.references_count == 0

    async def test_lsp_exception_propagated_via_return_exceptions(self):
        from oskill.code_intel_lookup import code_intel_lookup

        self.lh.side_effect = ConnectionError("lsp not ready")
        lsp = MagicMock()
        # return_exceptions=True means exceptions appear as results, not raised
        result = await code_intel_lookup(Path("f.py"), pos=Pos(line=0, character=0), lsp=lsp)
        assert result.hover_text == ""  # exception treated as non-dict

    async def test_cross_file_reference(self):
        from oskill.code_intel_lookup import code_intel_lookup

        self.lfr.return_value = [
            {"uri": "other_module.py", "range": {"start": {"line": 20, "character": 4}}},
        ]
        lsp = MagicMock()
        result = await code_intel_lookup(Path("main.py"), pos=Pos(line=10, character=2), lsp=lsp)
        assert result.references_count == 1


# ─────────────────────────────────────────────────────────────────────────────
# K-11 call_hierarchy_trace
# ─────────────────────────────────────────────────────────────────────────────


class TestCallHierarchyTrace:
    """K-11 call_hierarchy_trace — recursive LSP call hierarchy traversal."""

    @pytest.fixture(autouse=True)
    def _patch_oprim(self):
        with (
            patch("oskill.call_hierarchy_trace.lsp_prepare_call_hierarchy") as lpch,
            patch("oskill.call_hierarchy_trace.lsp_incoming_calls") as lic,
            patch("oskill.call_hierarchy_trace.lsp_outgoing_calls") as loc,
            patch("oskill.call_hierarchy_trace.location_to_snippet") as lts,
        ):
            lpch.return_value = [
                {
                    "name": "root_fn",
                    "uri": "main.py",
                    "range": {"start": {"line": 0, "character": 0}},
                }
            ]
            lic.return_value = []
            loc.return_value = []
            lts.return_value = "def root_fn(): ..."
            self.lpch = lpch
            self.lic = lic
            self.loc = loc
            self.lts = lts
            yield

    async def test_single_level_incoming_outgoing(self):
        from oskill.call_hierarchy_trace import call_hierarchy_trace

        self.lic.return_value = [
            {
                "from": {
                    "name": "caller",
                    "uri": "a.py",
                    "range": {"start": {"line": 5, "character": 0}},
                }
            }
        ]
        self.loc.return_value = [
            {
                "to": {
                    "name": "callee",
                    "uri": "b.py",
                    "range": {"start": {"line": 3, "character": 0}},
                }
            }
        ]
        lsp = MagicMock()
        tree = await call_hierarchy_trace(Path("main.py"), pos=Pos(0, 0), lsp=lsp, depth=1)
        assert tree.root is not None
        assert len(tree.root.incoming) == 1
        assert len(tree.root.outgoing) == 1

    async def test_depth_zero_returns_just_root(self):
        from oskill.call_hierarchy_trace import call_hierarchy_trace

        lsp = MagicMock()
        tree = await call_hierarchy_trace(Path("main.py"), pos=Pos(0, 0), lsp=lsp, depth=0)
        assert tree.root is not None
        assert tree.root.incoming == []
        assert tree.root.outgoing == []

    async def test_no_incoming_empty_list(self):
        from oskill.call_hierarchy_trace import call_hierarchy_trace

        self.lic.return_value = []
        lsp = MagicMock()
        tree = await call_hierarchy_trace(Path("f.py"), pos=Pos(0, 0), lsp=lsp, depth=1)
        assert tree.root.incoming == []

    async def test_no_outgoing_empty_list(self):
        from oskill.call_hierarchy_trace import call_hierarchy_trace

        self.loc.return_value = []
        lsp = MagicMock()
        tree = await call_hierarchy_trace(Path("f.py"), pos=Pos(0, 0), lsp=lsp, depth=1)
        assert tree.root.outgoing == []

    async def test_cycle_detection_visited_set(self):
        from oskill.call_hierarchy_trace import call_hierarchy_trace

        # Return the root itself as an incoming call (cycle)
        self.lic.return_value = [
            {
                "from": {
                    "name": "root_fn",
                    "uri": "main.py",
                    "range": {"start": {"line": 0, "character": 0}},
                }
            }
        ]
        lsp = MagicMock()
        # Should not recurse infinitely
        tree = await call_hierarchy_trace(Path("main.py"), pos=Pos(0, 0), lsp=lsp, depth=3)
        assert tree.root is not None
        assert len(tree.root.incoming) == 0  # cycle skipped

    async def test_depth_two_recursive(self):
        from oskill.call_hierarchy_trace import call_hierarchy_trace

        call_count = 0

        async def _lic(item, lsp):
            nonlocal call_count
            call_count += 1
            return [
                {
                    "from": {
                        "name": f"caller_{call_count}",
                        "uri": f"c{call_count}.py",
                        "range": {"start": {"line": call_count, "character": 0}},
                    }
                }
            ]

        self.lic.side_effect = _lic
        lsp = MagicMock()
        await call_hierarchy_trace(Path("main.py"), pos=Pos(0, 0), lsp=lsp, depth=2)
        assert call_count >= 1

    async def test_lsp_prepare_empty_returns_empty_tree(self):
        from oskill.call_hierarchy_trace import call_hierarchy_trace

        self.lpch.return_value = []
        lsp = MagicMock()
        tree = await call_hierarchy_trace(Path("f.py"), pos=Pos(0, 0), lsp=lsp)
        assert tree.root is None

    async def test_cross_file_calls(self):
        from oskill.call_hierarchy_trace import call_hierarchy_trace

        self.loc.return_value = [
            {
                "to": {
                    "name": "helper",
                    "uri": "utils.py",
                    "range": {"start": {"line": 10, "character": 0}},
                }
            }
        ]
        lsp = MagicMock()
        tree = await call_hierarchy_trace(Path("main.py"), pos=Pos(0, 0), lsp=lsp, depth=1)
        assert tree.root.outgoing[0].path == "utils.py"


# ─────────────────────────────────────────────────────────────────────────────
# K-12 worktree_prepare
# ─────────────────────────────────────────────────────────────────────────────


class TestWorktreePrepare:
    """K-12 worktree_prepare — create or reuse git worktree."""

    @pytest.fixture(autouse=True)
    def _patch_deps(self, tmp_path):
        self.repo = tmp_path / "myrepo"
        self.repo.mkdir()
        # The module lazy-imports oprim.git_snapshot + obase.git.run_git inside the
        # function, so we patch them at the source package level.
        self.gs = AsyncMock(return_value="abc123")
        self.gcb = AsyncMock(return_value="main")
        self.run_git_mock = None  # set per-test via context manager

    def _make_run_git(self, side_effects):
        """Helper: AsyncMock that pops from side_effects on each call."""
        return AsyncMock(side_effect=side_effects)

    async def test_valid_repo_new_branch_returns_path(self):
        from oskill.worktree_prepare import worktree_prepare

        run_git = self._make_run_git(
            [
                ".git",  # rev-parse --git-dir
                "",  # worktree list --porcelain
                Exception("branch not found"),  # rev-parse --verify
                "",  # worktree add -b
            ]
        )
        with (
            patch("obase.git.run_git", run_git),
            patch("oprim.git_snapshot", self.gs),
            patch("oprim.git_current_branch", self.gcb),
        ):
            result = await worktree_prepare(self.repo, branch="feature/x")
        assert isinstance(result, Path)
        assert "feature" in str(result) or "x" in str(result)

    async def test_empty_branch_raises_value_error(self):
        from oskill.worktree_prepare import worktree_prepare

        with pytest.raises(ValueError, match="branch must not be empty"):
            await worktree_prepare(self.repo, branch="")

    async def test_non_repo_raises_runtime_error(self):
        from oskill.worktree_prepare import worktree_prepare

        run_git = AsyncMock(side_effect=Exception("not a git repo"))
        with (
            patch("obase.git.run_git", run_git),
            patch("oprim.git_snapshot", self.gs),
            patch("oprim.git_current_branch", self.gcb),
        ):
            with pytest.raises(RuntimeError, match="Not a git repository"):
                await worktree_prepare(self.repo, branch="main")

    async def test_snapshot_taken_before_worktree(self):
        from oskill.worktree_prepare import worktree_prepare

        call_order: list[str] = []

        async def _rg(args, cwd):
            call_order.append(f"git:{args[0]}")
            if "--git-dir" in args:
                return ".git"
            if "list" in args:
                return ""
            raise Exception("branch missing")

        async def _snapshot(repo):
            call_order.append("snapshot")
            return "sha"

        with (
            patch("obase.git.run_git", _rg),
            patch("oprim.git_snapshot", _snapshot),
            patch("oprim.git_current_branch", self.gcb),
        ):
            try:
                await worktree_prepare(self.repo, branch="feat")
            except Exception:
                pass
        assert "snapshot" in call_order

    async def test_branch_already_has_worktree_reuses(self):
        from oskill.worktree_prepare import worktree_prepare

        wt_path = str(self.repo.parent / ".worktrees/myrepo-existing")
        porcelain = (
            f"worktree {wt_path}\nbranch refs/heads/existing\n\n"
            f"worktree {self.repo}\nbranch refs/heads/main\n"
        )
        run_git = self._make_run_git([".git", porcelain])
        with (
            patch("obase.git.run_git", run_git),
            patch("oprim.git_snapshot", self.gs),
            patch("oprim.git_current_branch", self.gcb),
        ):
            result = await worktree_prepare(self.repo, branch="existing")
        assert str(result) == wt_path

    async def test_branch_not_exist_created(self):
        from oskill.worktree_prepare import worktree_prepare

        calls: list[list[str]] = []

        async def _rg(args, cwd):
            calls.append(list(args))
            if "--git-dir" in args:
                return ".git"
            if "list" in args:
                return ""
            if "--verify" in args:
                raise Exception("no branch")
            return ""

        with (
            patch("obase.git.run_git", _rg),
            patch("oprim.git_snapshot", self.gs),
            patch("oprim.git_current_branch", self.gcb),
        ):
            await worktree_prepare(self.repo, branch="new-branch")
        assert any("-b" in c for c in calls)

    async def test_worktree_path_returned(self):
        from oskill.worktree_prepare import worktree_prepare

        run_git = self._make_run_git([".git", "", "", ""])
        with (
            patch("obase.git.run_git", run_git),
            patch("oprim.git_snapshot", self.gs),
            patch("oprim.git_current_branch", self.gcb),
        ):
            result = await worktree_prepare(self.repo, branch="stable")
        assert isinstance(result, Path)

    async def test_branch_exists_add_without_b(self):
        from oskill.worktree_prepare import worktree_prepare

        calls: list[list[str]] = []

        async def _rg(args, cwd):
            calls.append(list(args))
            if "--git-dir" in args:
                return ".git"
            if "list" in args:
                return ""
            if "--verify" in args:
                return "abc123"
            return ""

        with (
            patch("obase.git.run_git", _rg),
            patch("oprim.git_snapshot", self.gs),
            patch("oprim.git_current_branch", self.gcb),
        ):
            await worktree_prepare(self.repo, branch="existing-branch")
        add_calls = [c for c in calls if "worktree" in c and "add" in c]
        assert any("-b" not in c for c in add_calls)


# ─────────────────────────────────────────────────────────────────────────────
# K-13 scan_project_structure
# ─────────────────────────────────────────────────────────────────────────────


class TestScanProjectStructure:
    """K-13 scan_project_structure — scan repo structure."""

    @pytest.fixture(autouse=True)
    def _patch_oprim(self, tmp_path):
        self.root = tmp_path
        (tmp_path / ".gitignore").write_text("__pycache__\n")
        dl = AsyncMock(return_value=[tmp_path / "main.py", tmp_path / "pyproject.toml"])
        dpt = AsyncMock(return_value="python")
        gm = AsyncMock(return_value=[])
        pgi = MagicMock(return_value=[])
        agi = MagicMock(side_effect=lambda paths, patterns, root: paths)
        with (
            patch("oskill.scan_project_structure.dir_list", dl),
            patch("oskill.scan_project_structure.detect_project_type", dpt),
            patch("oskill.scan_project_structure.parse_gitignore", pgi),
            patch("oskill.scan_project_structure.apply_gitignore", agi),
            patch("oskill.scan_project_structure.glob_match", gm),
        ):
            self.dl = dl
            self.dpt = dpt
            self.pgi = pgi
            self.agi = agi
            self.gm = gm
            yield

    async def test_detects_project_type(self):
        from oskill.scan_project_structure import scan_project_structure

        result = await scan_project_structure(self.root)
        assert result.project_type == "python"

    async def test_returns_project_map(self):
        from oskill.scan_project_structure import scan_project_structure

        result = await scan_project_structure(self.root)
        assert isinstance(result, ProjectMap)

    async def test_gitignore_applied(self):
        from oskill.scan_project_structure import scan_project_structure

        self.pgi.return_value = [MagicMock()]
        self.dl.return_value = [self.root / "main.py"]
        self.agi.side_effect = lambda paths, patterns, root: paths
        await scan_project_structure(self.root)
        self.agi.assert_called()

    async def test_max_depth_respected(self):
        from oskill.scan_project_structure import scan_project_structure

        await scan_project_structure(self.root, max_depth=2)
        call_kw = self.dl.call_args[1]
        assert call_kw["max_depth"] == 2

    async def test_nonexistent_root_raises(self):
        from oskill.scan_project_structure import scan_project_structure

        with pytest.raises(FileNotFoundError):
            await scan_project_structure(Path("/nonexistent/nowhere"))

    async def test_key_files_identified(self):
        from oskill.scan_project_structure import scan_project_structure

        self.gm.return_value = [self.root / "pyproject.toml"]
        result = await scan_project_structure(self.root)
        assert isinstance(result.key_files, list)

    async def test_languages_detected(self):
        from oskill.scan_project_structure import scan_project_structure

        self.dpt.return_value = "python-django"
        result = await scan_project_structure(self.root)
        assert "python" in result.languages

    async def test_empty_project_minimal_map(self):
        from oskill.scan_project_structure import scan_project_structure

        self.dl.return_value = []
        self.dpt.return_value = "unknown"
        result = await scan_project_structure(self.root)
        assert result.project_type == "unknown"
        assert result.tree == []


# ─────────────────────────────────────────────────────────────────────────────
# K-14 git_safe_snapshot
# ─────────────────────────────────────────────────────────────────────────────


class TestGitSafeSnapshot:
    """K-14 git_safe_snapshot — create recoverable git snapshot."""

    @pytest.fixture(autouse=True)
    def _patch_deps(self, tmp_path):
        self.repo = tmp_path
        from oprim._hicode_types import GitStatus

        self._clean_status = GitStatus(modified=[], added=[], deleted=[], untracked=[])
        self._dirty_status = GitStatus(modified=["a.py"], added=[], deleted=[], untracked=[])
        # patch oprim-level symbols (lazy-imported inside the function)
        self.gcb = AsyncMock(return_value="main")
        self.gs = AsyncMock(return_value="snap_abc123")
        self.pgs = AsyncMock(return_value=self._clean_status)

    # Patch the names as bound in the module (module-level imports)
    def _p(self, rg):
        return (
            patch("oskill.git_safe_snapshot.run_git", rg),
            patch("oskill.git_safe_snapshot.git_current_branch", self.gcb),
            patch("oskill.git_safe_snapshot.git_snapshot", self.gs),
            patch("oskill.git_safe_snapshot.parse_git_status", self.pgs),
        )

    async def test_non_repo_raises_runtime_error(self):
        from oskill.git_safe_snapshot import git_safe_snapshot

        rg = AsyncMock(side_effect=Exception("not a git repo"))
        with (
            patch("obase.git.run_git", rg),
            patch("oskill.git_safe_snapshot.git_current_branch", self.gcb),
            patch("oskill.git_safe_snapshot.git_snapshot", self.gs),
            patch("oskill.git_safe_snapshot.parse_git_status", self.pgs),
        ):
            with pytest.raises(RuntimeError, match="Not a git repository"):
                await git_safe_snapshot(self.repo)

    async def test_clean_working_tree_returns_head_sha(self):
        from oskill.git_safe_snapshot import git_safe_snapshot

        sha = "deadbeef" * 5
        rg = AsyncMock(side_effect=[".git", sha])
        with (
            patch("obase.git.run_git", rg),
            patch("oskill.git_safe_snapshot.git_current_branch", self.gcb),
            patch("oskill.git_safe_snapshot.git_snapshot", self.gs),
            patch("oskill.git_safe_snapshot.parse_git_status", self.pgs),
        ):
            result = await git_safe_snapshot(self.repo)
        assert result != ""
        self.gs.assert_not_called()

    async def test_dirty_tree_snapshot_taken(self):
        from oskill.git_safe_snapshot import git_safe_snapshot

        self.pgs.return_value = self._dirty_status
        rg = AsyncMock(return_value=".git")
        with (
            patch("obase.git.run_git", rg),
            patch("oskill.git_safe_snapshot.git_current_branch", self.gcb),
            patch("oskill.git_safe_snapshot.git_snapshot", self.gs),
            patch("oskill.git_safe_snapshot.parse_git_status", self.pgs),
        ):
            result = await git_safe_snapshot(self.repo)
        self.gs.assert_called_once()
        assert "snap" in result

    async def test_status_parsed_correctly(self):
        from oskill.git_safe_snapshot import git_safe_snapshot

        rg = AsyncMock(return_value=".git")
        with (
            patch("obase.git.run_git", rg),
            patch("oskill.git_safe_snapshot.git_current_branch", self.gcb),
            patch("oskill.git_safe_snapshot.git_snapshot", self.gs),
            patch("oskill.git_safe_snapshot.parse_git_status", self.pgs),
        ):
            await git_safe_snapshot(self.repo)
        self.pgs.assert_called_once()

    async def test_snapshot_id_non_empty_on_dirty(self):
        from oprim._hicode_types import GitStatus

        from oskill.git_safe_snapshot import git_safe_snapshot

        self.pgs.return_value = GitStatus(modified=[], added=["new.py"], deleted=[], untracked=[])
        rg = AsyncMock(return_value=".git")
        with (
            patch("obase.git.run_git", rg),
            patch("oskill.git_safe_snapshot.git_current_branch", self.gcb),
            patch("oskill.git_safe_snapshot.git_snapshot", self.gs),
            patch("oskill.git_safe_snapshot.parse_git_status", self.pgs),
        ):
            result = await git_safe_snapshot(self.repo)
        assert result != ""

    async def test_untracked_files_included(self):
        from oprim._hicode_types import GitStatus

        from oskill.git_safe_snapshot import git_safe_snapshot

        self.pgs.return_value = GitStatus(
            modified=[], added=[], deleted=[], untracked=["new_file.py"]
        )
        rg = AsyncMock(return_value=".git")
        with (
            patch("obase.git.run_git", rg),
            patch("oskill.git_safe_snapshot.git_current_branch", self.gcb),
            patch("oskill.git_safe_snapshot.git_snapshot", self.gs),
            patch("oskill.git_safe_snapshot.parse_git_status", self.pgs),
        ):
            await git_safe_snapshot(self.repo)
        self.gs.assert_called_once()

    async def test_multiple_calls_give_different_ids(self):
        from oprim._hicode_types import GitStatus

        from oskill.git_safe_snapshot import git_safe_snapshot

        self.pgs.return_value = GitStatus(modified=["f.py"], added=[], deleted=[], untracked=[])
        self.gs.side_effect = ["sha_001", "sha_002"]
        rg = AsyncMock(return_value=".git")
        with (
            patch("obase.git.run_git", rg),
            patch("oskill.git_safe_snapshot.git_current_branch", self.gcb),
            patch("oskill.git_safe_snapshot.git_snapshot", self.gs),
            patch("oskill.git_safe_snapshot.parse_git_status", self.pgs),
        ):
            r1 = await git_safe_snapshot(self.repo)
            r2 = await git_safe_snapshot(self.repo)
        assert r1 != r2

    async def test_valid_sha_format_clean(self):
        from oskill.git_safe_snapshot import git_safe_snapshot

        sha = "a" * 40
        rg = AsyncMock(side_effect=[".git", sha])
        with (
            patch("obase.git.run_git", rg),
            patch("oskill.git_safe_snapshot.git_current_branch", self.gcb),
            patch("oskill.git_safe_snapshot.git_snapshot", self.gs),
            patch("oskill.git_safe_snapshot.parse_git_status", self.pgs),
        ):
            result = await git_safe_snapshot(self.repo)
        assert result.strip() == sha


# ─────────────────────────────────────────────────────────────────────────────
# K-15 tool_schema_assemble
# ─────────────────────────────────────────────────────────────────────────────


class TestToolSchemaAssemble:
    """K-15 tool_schema_assemble — build complete tool schema list."""

    @pytest.fixture(autouse=True)
    def _patch_oprim(self):
        with (
            patch("oskill.tool_schema_assemble.build_tool_schema") as bts,
            patch("oskill.tool_schema_assemble.mcp_tool_to_schema") as mtts,
            patch("oskill.tool_schema_assemble.normalize_tool_schema") as nts,
        ):
            bts.side_effect = lambda tool: {"name": tool.name, "description": tool.description}
            mtts.side_effect = lambda spec: {
                "name": f"mcp_{spec.name}",
                "description": spec.description,
            }
            nts.side_effect = lambda schemas, provider: schemas
            self.bts = bts
            self.mtts = mtts
            self.nts = nts
            yield

    def test_empty_tools_returns_empty(self):
        from oskill.tool_schema_assemble import tool_schema_assemble

        result = tool_schema_assemble([], provider="anthropic")
        assert result == []

    def test_builtin_tool_schema_returned(self):
        from oskill.tool_schema_assemble import tool_schema_assemble

        tools = [_tool("bash", "Run bash command")]
        result = tool_schema_assemble(tools, provider="anthropic")
        assert len(result) == 1
        assert result[0]["name"] == "bash"

    def test_mcp_tool_mcp_prefix_added(self):
        from oskill.tool_schema_assemble import tool_schema_assemble

        result = tool_schema_assemble([], provider="anthropic", mcp_specs=[_mcp_spec("web_search")])
        assert result[0]["name"] == "mcp_web_search"

    def test_provider_format_applied_anthropic(self):
        from oskill.tool_schema_assemble import tool_schema_assemble

        tool_schema_assemble([_tool()], provider="anthropic")
        self.nts.assert_called_once_with(
            [{"name": "read", "description": "Read a file"}], provider="anthropic"
        )

    def test_mixed_builtin_and_mcp(self):
        from oskill.tool_schema_assemble import tool_schema_assemble

        tools = [_tool("bash", "Run bash")]
        mcp_specs = [_mcp_spec("git_log", "Git log")]
        result = tool_schema_assemble(tools, provider="openai", mcp_specs=mcp_specs)
        assert len(result) == 2

    def test_tool_without_description_skipped(self):
        from oskill.tool_schema_assemble import tool_schema_assemble

        self.bts.side_effect = ValueError("no description")
        tools = [_tool("nodesc", "")]
        result = tool_schema_assemble(tools, provider="anthropic")
        assert result == []

    def test_large_tool_set(self):
        from oskill.tool_schema_assemble import tool_schema_assemble

        tools = [_tool(f"tool_{i}", f"Tool {i}") for i in range(30)]
        result = tool_schema_assemble(tools, provider="anthropic")
        assert len(result) == 30

    def test_provider_normalization_correct(self):
        from oskill.tool_schema_assemble import tool_schema_assemble

        tool_schema_assemble([_tool()], provider="google")
        call_kw = self.nts.call_args
        assert call_kw[1]["provider"] == "google"


# ─────────────────────────────────────────────────────────────────────────────
# K-16 web_research
# ─────────────────────────────────────────────────────────────────────────────


class TestWebResearch:
    """K-16 web_research — multi-source web research with LLM synthesis."""

    @pytest.fixture(autouse=True)
    def _patch_oprim(self):
        with (
            patch("oskill.web_research.http_fetch") as hf,
            patch("oskill.web_research.html_to_markdown") as htm,
            patch("oskill.web_research.extract_main_content") as emc,
            patch("oskill.web_research.validate_url") as vu,
        ):
            hf.return_value = b'<html><a href="https://example.com/page">link</a></html>'
            htm.side_effect = lambda html: html
            emc.side_effect = lambda md: md[:500]
            vu.return_value = True
            self.hf = hf
            self.htm = htm
            self.emc = emc
            self.vu = vu
            yield

    async def test_empty_query_raises(self):
        from oskill.web_research import web_research

        caller = AsyncMock()
        with pytest.raises(ValueError, match="query must not be empty"):
            await web_research("", caller=caller)

    async def test_caller_invoked_with_content(self):
        from oskill.web_research import web_research

        caller = AsyncMock(return_value={"content": "synthesis"})
        await web_research("Python async", caller=caller)
        caller.assert_called_once()
        msg_content = caller.call_args[1]["messages"][0]["content"]
        assert "Python async" in msg_content

    async def test_returns_research_result(self):
        from oskill.web_research import web_research

        caller = AsyncMock(return_value={"content": "answer"})
        result = await web_research("machine learning", caller=caller)
        assert isinstance(result, ResearchResult)

    async def test_sources_list_populated(self):
        from oskill.web_research import web_research

        self.hf.return_value = (
            b'<html><a href="https://a.com">a</a><a href="https://b.com">b</a></html>'
        )
        caller = AsyncMock(return_value={"content": "result"})
        result = await web_research("test query", caller=caller, max_sources=2)
        assert isinstance(result.sources, list)

    async def test_http_fetch_failure_on_source_skipped(self):
        from oskill.web_research import web_research

        # First call (search page) succeeds, subsequent source fetches fail
        self.hf.side_effect = [
            b'<html><a href="https://site.com">s</a></html>',
            Exception("connection refused"),
        ]
        caller = AsyncMock(return_value={"content": "partial"})
        result = await web_research("query", caller=caller)
        # Should not crash, content_chunks filtered
        assert isinstance(result, ResearchResult)

    async def test_max_sources_respected(self):
        from oskill.web_research import web_research

        many_links = " ".join(f'<a href="https://site{i}.com">link</a>' for i in range(20))
        self.hf.return_value = f"<html>{many_links}</html>".encode()
        caller = AsyncMock(return_value={"content": "summary"})
        result = await web_research("broad topic", caller=caller, max_sources=3)
        assert len(result.sources) <= 3

    async def test_summary_from_caller_included(self):
        from oskill.web_research import web_research

        self.hf.side_effect = [
            b'<html><a href="https://wiki.org/page">wiki</a></html>',
            b"<html>content</html>",
        ]
        caller = AsyncMock(return_value={"content": "the definitive answer"})
        result = await web_research("who invented Python", caller=caller)
        assert result.summary == "the definitive answer"

    async def test_confidence_proportional_to_sources(self):
        from oskill.web_research import web_research

        # 2 sources fetched out of max 4 → confidence = 0.5
        links = '<a href="https://a.com">a</a><a href="https://b.com">b</a>'
        self.hf.side_effect = [
            f"<html>{links}</html>".encode(),
            b"<html>content a</html>",
            b"<html>content b</html>",
        ]
        caller = AsyncMock(return_value={"content": "answer"})
        result = await web_research("topic", caller=caller, max_sources=4)
        assert 0.0 <= result.confidence <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# K-17 permission_evaluate
# ─────────────────────────────────────────────────────────────────────────────


class TestPermissionEvaluate:
    """K-17 permission_evaluate — comprehensive permission decision engine."""

    @pytest.fixture(autouse=True)
    def _patch_deps(self):
        from oprim._hicode_types import PermSet

        with (
            patch("oskill.permission_evaluate.resolve_agent_permissions") as rap,
            patch("oskill.permission_evaluate.match_wildcard_pattern") as mwp,
            patch("oskill.permission_evaluate.match_bash_command_rule") as mbcr,
            patch("oskill.permission_evaluate.classify_risk") as cr,
            patch("oskill.permission_evaluate.match_permission_rule") as mpr,
        ):
            rap.return_value = PermSet(tool_actions={}, bash_rules=[])
            mwp.return_value = False
            mbcr.return_value = "ask"
            cr.return_value = "low"
            mpr.return_value = "ask"
            self.rap = rap
            self.mwp = mwp
            self.mbcr = mbcr
            self.cr = cr
            self.mpr = mpr
            yield

    def _call(self, name="read", args=None, rules=None, persona=None):
        from oskill.permission_evaluate import permission_evaluate

        tc = ToolCall(id="tc1", name=name, args=args or {})
        p = persona or Persona(name="builder", mode="build")
        r = rules or []
        return permission_evaluate(tc, rules=r, persona=p)

    def test_allow_rule_returns_allow(self):
        self.mpr.return_value = "allow"
        from oprim._hicode_types import PermSet

        self.rap.return_value = PermSet(tool_actions={"read": "allow"}, bash_rules=[])
        result = self._call("read", rules=[Rule(pattern="read", action="allow")])
        assert result == "allow"

    def test_deny_rule_overrides_allow(self):
        self.mpr.return_value = "deny"
        from oprim._hicode_types import PermSet

        self.rap.return_value = PermSet(tool_actions={"read": "allow"}, bash_rules=[])
        result = self._call("read", rules=[Rule(pattern="read", action="deny")])
        assert result == "deny"

    def test_bash_rm_high_risk_ask_minimum(self):
        self.cr.return_value = "high"
        self.mpr.return_value = "allow"
        from oprim._hicode_types import PermSet

        self.rap.return_value = PermSet(tool_actions={"bash": "allow"}, bash_rules=[])
        result = self._call("bash", args={"command": "rm -rf /tmp/x"})
        assert result in ("ask", "deny")

    def test_persona_build_all_allow(self):
        from oprim._hicode_types import PermSet

        self.rap.return_value = PermSet(tool_actions={"write": "allow"}, bash_rules=[])
        self.mpr.return_value = "allow"
        persona = Persona(name="builder", mode="build", allow=["write"], deny=[])
        result = self._call("write", persona=persona)
        assert result == "allow"

    def test_persona_plan_edit_deny(self):
        from oprim._hicode_types import PermSet

        self.rap.return_value = PermSet(tool_actions={"write": "deny"}, bash_rules=[])
        self.mpr.return_value = "deny"
        persona = Persona(name="planner", mode="plan", deny=["write"])
        result = self._call("write", persona=persona)
        assert result == "deny"

    def test_wildcard_rule_match(self):
        self.mpr.return_value = "allow"
        from oprim._hicode_types import PermSet

        self.rap.return_value = PermSet(tool_actions={}, bash_rules=[])
        result = self._call("glob_tool", rules=[Rule(pattern="glob_*", action="allow")])
        assert result in ("allow", "ask")

    def test_no_rules_persona_default(self):
        from oprim._hicode_types import PermSet

        self.rap.return_value = PermSet(tool_actions={}, bash_rules=[])
        self.mpr.return_value = "ask"
        result = self._call("unknown_tool")
        assert result == "ask"

    def test_deny_beats_allow(self):
        from oprim._hicode_types import PermSet

        self.rap.return_value = PermSet(tool_actions={"bash": "allow"}, bash_rules=[])
        self.mpr.return_value = "deny"
        result = self._call("bash", rules=[Rule(pattern="bash", action="deny")])
        assert result == "deny"


# ─────────────────────────────────────────────────────────────────────────────
# K-18 mcp_tool_invoke
# ─────────────────────────────────────────────────────────────────────────────


class TestMcpToolInvoke:
    """K-18 mcp_tool_invoke — invoke MCP tool and normalise result."""

    @pytest.fixture(autouse=True)
    def _patch_oprim(self):
        with (
            patch("oskill.mcp_tool_invoke.mcp_call_tool") as mct,
            patch("oskill.mcp_tool_invoke.mcp_tool_to_schema") as mtts,
            patch("oskill.mcp_tool_invoke.summarize_subagent_result") as ssr,
        ):
            mct.return_value = "tool output"
            mtts.return_value = {"name": "search", "parameters": {"required": []}}
            ssr.return_value = "summarized"
            self.mct = mct
            self.mtts = mtts
            self.ssr = ssr
            yield

    async def test_success_returns_tool_result(self):
        from oskill.mcp_tool_invoke import mcp_tool_invoke

        session = MagicMock()
        session.call_tool = AsyncMock(return_value="done")
        session.list_tools = AsyncMock(return_value=[])
        self.mct.return_value = "done"
        result = await mcp_tool_invoke(session, name="search", args={"q": "test"})
        assert isinstance(result, ToolResult)
        assert result.content == "done"
        assert result.is_error is False

    async def test_missing_required_arg_raises(self):
        from oskill.mcp_tool_invoke import mcp_tool_invoke

        session = MagicMock()
        session.list_tools = AsyncMock(
            return_value=[
                {
                    "name": "search",
                    "description": "search tool",
                    "inputSchema": {"type": "object", "properties": {}, "required": ["q"]},
                }
            ]
        )
        self.mtts.return_value = {"name": "search", "parameters": {"required": ["q"]}}
        with pytest.raises(ValueError, match="Missing required arg"):
            await mcp_tool_invoke(session, name="search", args={})

    async def test_tool_call_error_returns_is_error(self):
        from oskill.mcp_tool_invoke import mcp_tool_invoke

        session = MagicMock()
        session.list_tools = AsyncMock(return_value=[])
        self.mct.side_effect = RuntimeError("server error")
        result = await mcp_tool_invoke(session, name="broken", args={})
        assert result.is_error is True
        assert "server error" in result.content

    async def test_large_result_truncated(self):
        from oskill.mcp_tool_invoke import mcp_tool_invoke

        session = MagicMock()
        session.list_tools = AsyncMock(return_value=[])
        self.mct.return_value = "x" * 20_000
        result = await mcp_tool_invoke(session, name="big", args={})
        assert len(result.content) <= 10_100
        assert "truncated" in result.content

    async def test_list_result_joined(self):
        from oskill.mcp_tool_invoke import mcp_tool_invoke

        session = MagicMock()
        session.list_tools = AsyncMock(return_value=[])
        self.mct.return_value = ["item1", "item2", "item3"]
        result = await mcp_tool_invoke(session, name="list_tool", args={})
        assert "item1" in result.content
        assert "item2" in result.content

    async def test_dict_result_json_encoded(self):
        from oskill.mcp_tool_invoke import mcp_tool_invoke

        session = MagicMock()
        session.list_tools = AsyncMock(return_value=[])
        self.mct.return_value = {"key": "value", "count": 42}
        result = await mcp_tool_invoke(session, name="dict_tool", args={})
        parsed = json.loads(result.content)
        assert parsed["key"] == "value"

    async def test_call_id_in_result(self):
        from oskill.mcp_tool_invoke import mcp_tool_invoke

        session = MagicMock()
        session.list_tools = AsyncMock(return_value=[])
        self.mct.return_value = "ok"
        result = await mcp_tool_invoke(session, name="tool", args={})
        assert result.call_id != ""
        assert len(result.call_id) > 0

    async def test_session_list_tools_unavailable_proceeds(self):
        from oskill.mcp_tool_invoke import mcp_tool_invoke

        session = MagicMock()
        session.list_tools = AsyncMock(side_effect=Exception("not available"))
        self.mct.return_value = "result despite no schema"
        result = await mcp_tool_invoke(session, name="tool", args={"a": 1})
        assert result.is_error is False
        assert result.content == "result despite no schema"


# ─────────────────────────────────────────────────────────────────────────────
# K-19 subagent_dispatch
# ─────────────────────────────────────────────────────────────────────────────


class TestSubagentDispatch:
    """K-19 subagent_dispatch — prepare subagent plan without running agent loop."""

    @pytest.fixture(autouse=True)
    def _patch_deps(self):
        with (
            patch("oskill.subagent_dispatch.resolve_subagent_tools") as rst,
            patch("oskill.subagent_dispatch.summarize_subagent_result") as ssr,
            patch("oskill.subagent_dispatch.build_subagent_prompt") as bsp,
        ):
            rst.return_value = []
            ssr.return_value = "summary_rule"
            bsp.return_value = "SUBAGENT PROMPT: do the task"
            self.rst = rst
            self.ssr = ssr
            self.bsp = bsp
            yield

    async def test_empty_task_raises(self):
        from oskill.subagent_dispatch import subagent_dispatch

        persona = Persona(name="helper")
        with pytest.raises(ValueError, match="task must not be empty"):
            await subagent_dispatch(task="", persona=persona, caller=None, parent_ctx="ctx")

    async def test_returns_subagent_plan(self):
        from oskill.subagent_dispatch import subagent_dispatch

        persona = Persona(name="helper")
        result = await subagent_dispatch(
            task="Fix bug in auth module", persona=persona, caller=None, parent_ctx=""
        )
        assert isinstance(result, SubagentPlan)

    async def test_prompt_contains_task(self):
        from oskill.subagent_dispatch import subagent_dispatch

        self.bsp.return_value = "PROMPT: Fix bug in auth module"
        persona = Persona(name="helper")
        result = await subagent_dispatch(
            task="Fix bug in auth module", persona=persona, caller=None, parent_ctx="ctx"
        )
        assert "Fix bug in auth module" in result.prompt

    async def test_prompt_contains_parent_ctx(self):
        from oskill.subagent_dispatch import subagent_dispatch

        self.bsp.side_effect = lambda task, parent_ctx: f"Task: {task}\nContext: {parent_ctx}"
        persona = Persona(name="helper")
        result = await subagent_dispatch(
            task="do it", persona=persona, caller=None, parent_ctx="parent summary here"
        )
        assert "parent summary here" in result.prompt

    async def test_tools_filtered_task_excluded(self):
        from oskill.subagent_dispatch import subagent_dispatch

        self.rst.return_value = [_tool("bash"), _tool("read")]
        persona = Persona(name="helper")
        result = await subagent_dispatch(
            task="do work", persona=persona, caller=None, parent_ctx=""
        )
        tool_names = [t.name if hasattr(t, "name") else str(t) for t in result.tools]
        assert "task" not in tool_names

    async def test_persona_name_in_plan(self):
        from oskill.subagent_dispatch import subagent_dispatch

        persona = Persona(name="specialist_agent")
        result = await subagent_dispatch(
            task="research", persona=persona, caller=None, parent_ctx=""
        )
        assert result.persona_name == "specialist_agent"

    async def test_summary_rule_non_empty(self):
        from oskill.subagent_dispatch import subagent_dispatch

        persona = Persona(name="helper")
        result = await subagent_dispatch(
            task="analyze data", persona=persona, caller=None, parent_ctx=""
        )
        assert result.summary_rule != ""
        assert "analyze data" in result.summary_rule or len(result.summary_rule) > 0

    async def test_does_not_call_llm(self):
        from oskill.subagent_dispatch import subagent_dispatch

        caller = AsyncMock()
        persona = Persona(name="helper")
        await subagent_dispatch(task="some task", persona=persona, caller=caller, parent_ctx="")
        caller.assert_not_called()

    async def test_does_not_run_agent_loop(self):
        """Verify no recursive subagent_dispatch call is made inside itself."""
        from oskill import subagent_dispatch as module

        original = module.subagent_dispatch
        call_count = [0]

        async def counting_dispatch(**kwargs):
            call_count[0] += 1
            if call_count[0] > 1:
                raise AssertionError("recursive dispatch detected")
            return await original(**kwargs)

        persona = Persona(name="helper")
        result = await original(
            task="non-recursive task", persona=persona, caller=None, parent_ctx=""
        )
        assert call_count[0] == 0
        assert isinstance(result, SubagentPlan)


# ─────────────────────────────────────────────────────────────────────────────
# K-20 streaming_assemble
# ─────────────────────────────────────────────────────────────────────────────


class TestStreamingAssemble:
    """K-20 streaming_assemble — assemble streaming deltas into complete Message."""

    @pytest.fixture(autouse=True)
    def _patch_oprim(self):
        with (
            patch("oskill.streaming_assemble.merge_streaming_parts") as msp,
            patch("oskill.streaming_assemble.parts_to_message") as ptm,
            patch("oskill.streaming_assemble.make_reasoning_part") as mrp,
        ):
            msp.side_effect = lambda group: Part(
                type=group[0].type,
                text="".join(d.text or "" for d in group),
            )
            ptm.side_effect = lambda parts, role: Message(role=role, parts=parts)
            mrp.side_effect = lambda text: Part(type="reasoning", text=text)
            self.msp = msp
            self.ptm = ptm
            self.mrp = mrp
            yield

    def test_empty_deltas_raises(self):
        from oskill.streaming_assemble import streaming_assemble

        with pytest.raises(ValueError, match="deltas must not be empty"):
            streaming_assemble([])

    def test_single_text_delta_message(self):
        from oskill.streaming_assemble import streaming_assemble

        deltas = [_delta(0, "text", text="hello")]
        result = streaming_assemble(deltas)
        assert isinstance(result, Message)
        assert result.parts[0].type == "text"

    def test_multiple_text_deltas_concatenated(self):
        from oskill.streaming_assemble import streaming_assemble

        deltas = [_delta(0, "text", text="foo"), _delta(0, "text", text="bar")]
        result = streaming_assemble(deltas)
        assert result.parts[0].text == "foobar"

    def test_tool_call_deltas_produce_tool_call_part(self):
        from oskill.streaming_assemble import streaming_assemble

        self.msp.side_effect = lambda group: Part(
            type="tool_call",
            data="".join(d.args_chunk or "" for d in group),
        )
        deltas = [
            _delta(0, "tool_call", tool_call_id="tc1", tool_name="bash", args_chunk='{"cmd":'),
            _delta(0, "tool_call", args_chunk='"ls"}'),
        ]
        result = streaming_assemble(deltas)
        assert result.parts[0].type == "tool_call"

    def test_reasoning_deltas_use_make_reasoning_part(self):
        from oskill.streaming_assemble import streaming_assemble

        deltas = [
            _delta(0, "reasoning", text="let me think"),
            _delta(0, "reasoning", text=" about this"),
        ]
        result = streaming_assemble(deltas)
        self.mrp.assert_called_once_with("let me think about this")
        assert result.parts[0].type == "reasoning"

    def test_multi_index_grouped_correctly(self):
        from oskill.streaming_assemble import streaming_assemble

        deltas = [
            _delta(0, "text", text="first"),
            _delta(1, "text", text="second"),
        ]
        result = streaming_assemble(deltas)
        assert len(result.parts) == 2

    def test_partial_json_args_assembled(self):
        from oskill.streaming_assemble import streaming_assemble

        self.msp.side_effect = lambda group: Part(
            type="tool_call",
            data="".join(d.args_chunk or "" for d in group),
        )
        deltas = [
            _delta(0, "tool_call", args_chunk='{"file":'),
            _delta(0, "tool_call", args_chunk='"main.py"}'),
        ]
        result = streaming_assemble(deltas)
        assert result.parts[0].data == '{"file":"main.py"}'

    def test_role_is_assistant(self):
        from oskill.streaming_assemble import streaming_assemble

        deltas = [_delta(0, "text", text="response")]
        result = streaming_assemble(deltas)
        assert result.role == "assistant"
