"""Auto-split from hicode whl."""

from __future__ import annotations
from oskill import apply_edit_block, syntax_check
from oprim import detect_language

from typing import Any



from ._types import EditBlock
from .edit import apply_edit_block


def validate_edit(
    original: str,
    edit: dict[str, Any],
    *,
    language: str | None = None,
) -> dict[str, Any]:
    """应用编辑后做语法校验（纯内存）。

    组合：apply_edit_block（本文件同批）+ syntax_check。

    Args:
        original: 原始文件内容。
        edit: edit dict，含 full_content / blocks / unified_diff 之一。
        language: 语言标识，空时从 edit.get("path") 检测。

    Returns:
        {
            "ok": bool,
            "content": str,      # 应用后的内容
            "errors": list[dict], # 语法错误列表
            "conflicts": list,   # edit 冲突
        }

    Example:
        >>> result = validate_edit("x = 1\\n",
        ...     {"path": "f.py", "blocks": [{"search": "x = 1", "replace": "x = "}]})
        >>> result["ok"]
        False  # 语法错误
    """
    path = edit.get("path", "")
    lang = language or (detect_language(path) if path else None)
    conflicts: list[str] = []
    new_content = original

    if "full_content" in edit:
        new_content = edit["full_content"]
    elif "blocks" in edit:
        blocks = [
            EditBlock(b["search"], b["replace"]) if isinstance(b, dict) else b
            for b in edit["blocks"]
        ]
        result = apply_edit_block(original, blocks=blocks)
        new_content = result.content
        conflicts = result.conflicts
    # unified_diff 分支由 apply_unified_diff 处理，validate_edit 不重复

    errors = syntax_check(new_content, path=path, language=lang)
    return {
        "ok": len(errors) == 0 and len(conflicts) == 0,
        "content": new_content,
        "errors": errors,
        "conflicts": conflicts,
    }
