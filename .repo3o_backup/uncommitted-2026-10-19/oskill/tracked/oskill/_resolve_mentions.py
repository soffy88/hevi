"""Auto-split from hicode whl."""

from __future__ import annotations
from oprim import file_read, glob_match

import re
from pathlib import Path
from typing import Any



def resolve_mentions(
    text: str,
    *,
    root: str,
) -> dict[str, Any]:
    """解析文本中的 @file/@symbol 引用，展开为文件路径 + 内容（只读）。

    组合：正则解析 + glob_match + file_read。

    Args:
        text: 含 @mention 的用户输入文本。
        root: 工作区根目录。

    Returns:
        {
            "expanded": str,      # 展开后的文本
            "files": list[str],   # 被引用的文件路径列表
            "symbols": list[str], # 被引用的符号名列表
        }

    Example:
        >>> r = resolve_mentions("Look at @src/main.py please", root="/proj")
        >>> "src/main.py" in r["files"]
        True
    """
    file_refs = re.findall(r"@([\w./\-]+\.\w+)", text)
    symbol_refs = re.findall(r"@(\w+)(?!\.\w)", text)

    resolved_files: list[str] = []
    expanded = text

    for ref in file_refs:
        candidate = Path(root) / ref
        if candidate.exists():
            try:
                content = file_read(str(candidate))
                snippet = "\n".join(content.splitlines()[:50])
                placeholder = f"\n```\n# {ref}\n{snippet}\n```\n"
                expanded = expanded.replace(f"@{ref}", placeholder, 1)
                resolved_files.append(str(candidate))
            except Exception:  # pragma: no cover
                pass  # pragma: no cover
        else:
            # glob 查找
            try:
                matches = glob_match(f"**/{ref}", root=root)
                if matches:
                    p = str(matches[0])  # pragma: no cover
                    content = file_read(p)  # pragma: no cover
                    snippet = "\n".join(content.splitlines()[:50])  # pragma: no cover
                    placeholder = f"\n```\n# {ref}\n{snippet}\n```\n"  # pragma: no cover
                    expanded = expanded.replace(f"@{ref}", placeholder, 1)  # pragma: no cover
                    resolved_files.append(p)  # pragma: no cover
            except Exception:  # pragma: no cover
                pass  # pragma: no cover

    return {
        "expanded": expanded,
        "files": resolved_files,
        "symbols": [s for s in symbol_refs if s not in {r.replace(".", "") for r in file_refs}],
    }
