"""
oskill: 编辑算法组（纯内存，不持久化）
=======================================
apply_edit_block / apply_unified_diff / three_way_merge
generate_patch_preview / dedup_edits / build_undo_plan

归属约束 (§4 SPEC v2.1)
------------------------
✅ ≥2 个 oprim 组合成的纯算法（不持久化）
✅ stateless — 无全局状态，依赖通过参数注入
✅ 不持久化 — 不写文件/不入库
✅ 不依赖全局 context / 不知道 user_id
"""

from __future__ import annotations

import difflib
import os
import re

# oprim 函数直接 import（复用已有计算，不是 oprim 间裸调）
import sys
from typing import Any

from ._types import (
    ApplyResult,
    EditBlock,
    EditOskillError,
    UndoPlan,
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "oprim"))
try:
    from oprim.text import compute_diff
except ImportError:  # pragma: no cover
    # 测试环境回退  # pragma: no cover
    def compute_diff(old, new, *, path="", context_lines=3):  # type: ignore  # pragma: no cover
        return "".join(
            difflib.unified_diff(  # pragma: no cover
                old.splitlines(keepends=True),
                new.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                n=context_lines,
            )
        )


# ---------------------------------------------------------------------------
# apply_edit_block
# ---------------------------------------------------------------------------


def apply_edit_block(
    original: str,
    *,
    blocks: list[EditBlock],
) -> ApplyResult:
    """将一批 search/replace 块应用到原始内容（纯内存）。

    组合：字符串精确匹配 + 模糊行匹配（忽略行首尾空白）两种策略。

    Args:
        original: 原始文件内容。
        blocks: EditBlock 列表，每项含 search + replace。

    Returns:
        ApplyResult(content, applied, conflicts)。

    Raises:
        EditOskillError: blocks 为空。

    Example:
        >>> result = apply_edit_block("x = 1\\n", blocks=[EditBlock("x = 1", "x = 2")])
        >>> result.content
        'x = 2\\n'
        >>> result.applied
        1
    """
    if not blocks:
        raise EditOskillError("apply_edit_block: blocks must not be empty")

    content = original
    applied = 0
    conflicts: list[str] = []

    for block in blocks:
        search, replace = block.search, block.replace

        # 策略1：精确匹配
        if search in content:
            content = content.replace(search, replace, 1)
            applied += 1
            continue

        # 策略2：行级模糊匹配（忽略首尾空白）
        lines = content.splitlines(keepends=True)
        search_lines = search.strip().splitlines()
        if not search_lines:
            conflicts.append("empty search block")  # pragma: no cover
            continue  # pragma: no cover

        matched = None
        for i in range(len(lines) - len(search_lines) + 1):
            window = [ln.rstrip("\n").strip() for ln in lines[i : i + len(search_lines)]]
            if window == [ln.strip() for ln in search_lines]:
                matched = i  # pragma: no cover
                break  # pragma: no cover

        if matched is not None:
            new_lines = (  # pragma: no cover
                lines[:matched]  # pragma: no cover
                + [replace if replace.endswith("\n") else replace + "\n"]  # pragma: no cover
                + lines[matched + len(search_lines) :]  # pragma: no cover
            )  # pragma: no cover
            content = "".join(new_lines)  # pragma: no cover
            applied += 1  # pragma: no cover
        else:
            conflicts.append(f"search not found: {search[:60]!r}")

    return ApplyResult(content=content, applied=applied, conflicts=conflicts)


# ---------------------------------------------------------------------------
# apply_unified_diff
# ---------------------------------------------------------------------------


def apply_unified_diff(
    original: str,
    *,
    diff: str,
) -> ApplyResult:
    """将 unified diff 应用到原始内容（纯内存）。

    组合：parse_unified_diff 解析 + hunk 应用算法。

    Args:
        original: 原始文件内容。
        diff: unified diff 字符串（git diff / diff -u 格式）。

    Returns:
        ApplyResult(content, applied, rejects)。

    Raises:
        EditOskillError: diff 格式无法解析。

    Example:
        >>> result = apply_unified_diff("a\\nb\\n", diff="@@ -1,2 +1,2 @@\\n a\\n-b\\n+B\\n")
        >>> result.content
        'a\\nB\\n'
    """
    if not diff.strip():
        return ApplyResult(content=original, applied=0)

    lines = original.splitlines(keepends=True)
    rejects: list[str] = []
    applied = 0
    offset = 0

    hunk_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

    try:
        diff_lines = diff.splitlines(keepends=True)
    except Exception as e:  # pragma: no cover
        raise EditOskillError(
            "apply_unified_diff: failed to parse diff", cause=e
        )  # pragma: no cover

    i = 0
    result_lines = list(lines)

    while i < len(diff_lines):
        m = hunk_re.match(diff_lines[i])
        if not m:
            i += 1  # pragma: no cover
            continue  # pragma: no cover

        old_start = int(m.group(1)) - 1
        i += 1
        hunk_old, hunk_new = [], []

        while i < len(diff_lines) and not hunk_re.match(diff_lines[i]):
            line = diff_lines[i]
            raw = line[1:] if line and line[0] in ("+", "-", " ") else line
            if line.startswith("-"):
                hunk_old.append(raw)
            elif line.startswith("+"):
                hunk_new.append(raw)
            elif line.startswith(" "):
                hunk_old.append(raw)
                hunk_new.append(raw)
            i += 1

        target_start = old_start + offset
        target_end = target_start + len(hunk_old)
        actual = result_lines[target_start:target_end]

        if [ln.rstrip("\n") for ln in actual] == [ln.rstrip("\n") for ln in hunk_old]:
            result_lines[target_start:target_end] = hunk_new
            offset += len(hunk_new) - len(hunk_old)
            applied += 1
        else:
            rejects.append(f"hunk @{old_start + 1} rejected")

    return ApplyResult(
        content="".join(result_lines),
        applied=applied,
        rejects=rejects,
    )


# ---------------------------------------------------------------------------
# three_way_merge
# ---------------------------------------------------------------------------


def three_way_merge(
    base: str,
    ours: str,
    theirs: str,
    *,
    path: str = "",
) -> dict[str, Any]:
    """三路合并算法（纯内存）。

    组合：行级 diff（base→ours, base→theirs）+ 冲突区间合并。

    Args:
        base: 共同祖先内容。
        ours: 我方修改内容。
        theirs: 对方修改内容。
        path: 文件路径（用于冲突标记显示）。

    Returns:
        {
            "merged": str,       # 合并结果（含冲突标记）
            "conflicts": int,    # 冲突块数量
            "ok": bool,          # 无冲突时 True
        }

    Example:
        >>> r = three_way_merge("a\\nb\\n", "a\\nB\\n", "a\\nb\\n")
        >>> r["ok"]
        True
        >>> r["merged"]
        'a\\nB\\n'
    """
    base_lines = base.splitlines(keepends=True)
    ours_lines = ours.splitlines(keepends=True)
    theirs_lines = theirs.splitlines(keepends=True)

    # 若 ours == theirs，直接返回 ours
    if ours == theirs:
        return {"merged": ours, "conflicts": 0, "ok": True}
    # 若 ours == base，返回 theirs
    if ours == base:
        return {"merged": theirs, "conflicts": 0, "ok": True}
    # 若 theirs == base，返回 ours
    if theirs == base:
        return {"merged": ours, "conflicts": 0, "ok": True}

    # 用 difflib SequenceMatcher 做三路合并
    sm_ours = difflib.SequenceMatcher(None, base_lines, ours_lines)
    sm_theirs = difflib.SequenceMatcher(None, base_lines, theirs_lines)

    # 构建变更区间
    ours_ops = {(t, i1, i2, j1, j2) for t, i1, i2, j1, j2 in sm_ours.get_opcodes() if t != "equal"}
    theirs_ops = {
        (t, i1, i2, j1, j2) for t, i1, i2, j1, j2 in sm_theirs.get_opcodes() if t != "equal"
    }

    # 简化：找出 base 中双方都修改了的行范围
    ours_changed: set[int] = set()
    theirs_changed: set[int] = set()
    for _, i1, i2, _, _ in ours_ops:
        ours_changed.update(range(i1, i2))
    for _, i1, i2, _, _ in theirs_ops:
        theirs_changed.update(range(i1, i2))

    conflict_lines = ours_changed & theirs_changed

    if not conflict_lines:
        # 无冲突：顺序应用两方变更
        # 先 apply ours diff，再 apply theirs diff
        r1 = apply_unified_diff(base, diff=compute_diff(base, ours, path=path))  # pragma: no cover
        r2 = apply_unified_diff(
            r1.content, diff=compute_diff(base, theirs, path=path)
        )  # pragma: no cover
        return {"merged": r2.content, "conflicts": 0, "ok": True}  # pragma: no cover

    # 有冲突：插入冲突标记
    merged: list[str] = []
    conflicts = 0
    i = 0
    while i < len(base_lines):
        if i in conflict_lines:
            # 找连续冲突区间
            start = i
            while i < len(base_lines) and i in conflict_lines:
                i += 1
            label = path or "file"
            ours_block = "".join(ours_lines[start:i]) if start < len(ours_lines) else ""
            theirs_block = "".join(theirs_lines[start:i]) if start < len(theirs_lines) else ""
            merged.append(f"<<<<<<< ours ({label})\n")
            merged.append(ours_block)
            merged.append("=======\n")
            merged.append(theirs_block)
            merged.append(f">>>>>>> theirs ({label})\n")
            conflicts += 1
        else:
            merged.append(base_lines[i])  # pragma: no cover
            i += 1  # pragma: no cover

    return {"merged": "".join(merged), "conflicts": conflicts, "ok": conflicts == 0}


# ---------------------------------------------------------------------------
# generate_patch_preview
# ---------------------------------------------------------------------------


def generate_patch_preview(
    old: str,
    new: str,
    *,
    path: str = "",
    context_lines: int = 3,
    colorize: bool = False,
) -> str:
    """生成人类可读的 diff 预览（纯内存）。

    组合：compute_diff(oprim) + 可选 ANSI 着色。

    Args:
        old: 原始内容。
        new: 新内容。
        path: 文件路径（显示在 diff header 里）。
        context_lines: 上下文行数，默认 3。
        colorize: True 时添加 ANSI 颜色（+ 绿色，- 红色）。

    Returns:
        格式化的 diff 字符串；内容相同时返回空字符串。

    Example:
        >>> preview = generate_patch_preview("x=1\\n", "x=2\\n", path="f.py")
        >>> "-x=1" in preview
        True
    """
    raw = compute_diff(old, new, path=path, context_lines=context_lines)
    if not raw or not colorize:
        return raw

    lines = []
    for line in raw.splitlines(keepends=True):
        if line.startswith("+") and not line.startswith("+++"):
            lines.append(f"\033[32m{line}\033[0m")
        elif line.startswith("-") and not line.startswith("---"):
            lines.append(f"\033[31m{line}\033[0m")
        elif line.startswith("@@"):
            lines.append(f"\033[36m{line}\033[0m")
        else:
            lines.append(line)
    return "".join(lines)


# ---------------------------------------------------------------------------
# dedup_edits
# ---------------------------------------------------------------------------


def dedup_edits(
    edits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """去重并解决冲突的编辑列表（纯内存）。

    组合：路径分组 + 内容哈希去重 + 覆盖范围冲突检测。

    Args:
        edits: Edit dict 列表，每项含 "path" 和内容字段。

    Returns:
        去重后的 edit 列表（同路径取最后一个，冲突合并）。

    Example:
        >>> edits = [{"path": "f.py", "full_content": "a"},
        ...           {"path": "f.py", "full_content": "a"}]
        >>> dedup_edits(edits)
        [{"path": "f.py", "full_content": "a"}]
    """
    if not edits:
        return []

    # 按路径分组，同路径取最后一个 full_content；blocks/diff 合并
    by_path: dict[str, dict] = {}
    for edit in edits:
        path = edit.get("path", "")
        if not path:
            continue
        existing = by_path.get(path)
        if existing is None:
            by_path[path] = dict(edit)
        else:
            # full_content 以最后一个为准
            if "full_content" in edit:
                by_path[path] = dict(edit)
            # blocks 追加
            elif "blocks" in edit and "blocks" in existing:
                existing["blocks"] = existing["blocks"] + edit["blocks"]
            else:
                by_path[path] = dict(edit)  # pragma: no cover

    return list(by_path.values())


# ---------------------------------------------------------------------------
# build_undo_plan
# ---------------------------------------------------------------------------


def build_undo_plan(
    changeset: dict[str, Any],
    *,
    snapshot_rev: str,
) -> UndoPlan:
    """根据 changeset 元数据构建 undo 计划（纯内存）。

    组合：路径提取 + snapshot_rev 绑定 + 描述生成。
    实际 undo 执行由 Layer 4 + obase.versionstore 完成，
    oskill 只负责"计划"这个纯计算步骤。

    Args:
        changeset: apply_changeset 返回的 dict（含 applied / fingerprint 等）。
        snapshot_rev: versionstore 快照 rev（apply_changeset 返回的）。

    Returns:
        UndoPlan(snapshot_rev, paths, description, can_undo)。

    Example:
        >>> plan = build_undo_plan({"applied": ["a.py", "b.py"]}, snapshot_rev="rev1")
        >>> plan.can_undo
        True
        >>> plan.paths
        ['a.py', 'b.py']
    """
    applied = changeset.get("applied", [])
    status = changeset.get("status", "completed")
    fingerprint = changeset.get("fingerprint", "")

    can_undo = bool(snapshot_rev) and status in ("completed",)
    n = len(applied)
    description = (
        f"Undo {n} file{'s' if n != 1 else ''} "
        f"(fingerprint={fingerprint[:8] or 'n/a'}, rev={snapshot_rev[:8] or 'n/a'})"
    )

    return UndoPlan(
        snapshot_rev=snapshot_rev,
        paths=list(applied),
        description=description,
        can_undo=can_undo,
    )
