"""Auto-split from hicode whl."""

from __future__ import annotations
from oskill import apply_unified_diff
from oprim import compute_diff

import difflib
from typing import Any




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
