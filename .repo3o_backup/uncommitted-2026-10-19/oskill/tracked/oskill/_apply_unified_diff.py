"""Auto-split from hicode whl."""

from __future__ import annotations

import re

from ._types import ApplyResult, EditOskillError


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
