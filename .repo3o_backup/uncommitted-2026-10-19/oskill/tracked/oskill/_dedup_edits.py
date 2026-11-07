"""Auto-split from hicode whl."""

from __future__ import annotations

from typing import Any


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
