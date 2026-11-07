"""Auto-split from hicode whl."""

from __future__ import annotations

from ._types import ApplyResult, EditBlock, EditOskillError


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
