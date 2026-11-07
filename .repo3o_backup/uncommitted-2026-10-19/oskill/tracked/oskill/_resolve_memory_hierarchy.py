"""Auto-split from hicode whl."""

from __future__ import annotations
from oprim import file_read

import re
from pathlib import Path
from typing import Any



def resolve_memory_hierarchy(
    *,
    enterprise: str | None = None,
    project: str | None = None,
    user: str | None = None,
    local: str | None = None,
    max_imports: int = 10,
) -> dict[str, Any]:
    """解析四层 CLAUDE.md 记忆层级，支持 @import 递归（只读）。

    组合：file_read + @import 解析（递归，最多 max_imports 次）。
    优先级：local > user > project > enterprise。

    Args:
        enterprise: enterprise 级 CLAUDE.md 路径（可选）。
        project: project 级 CLAUDE.md 路径（可选）。
        user: user 级 CLAUDE.md 路径（可选）。
        local: local 级 CLAUDE.md 路径（可选）。
        max_imports: @import 最大递归次数，默认 10。

    Returns:
        {
            "content": str,       # 合并后的记忆内容
            "sources": list[str], # 实际读取的文件路径
            "import_count": int,
        }

    Example:
        >>> mem = resolve_memory_hierarchy(project="/project/CLAUDE.md")
        >>> isinstance(mem["content"], str)
        True
    """
    layers = [enterprise, project, user, local]
    parts: list[str] = []
    sources: list[str] = []
    import_count = 0

    def read_with_imports(path: str, depth: int = 0) -> str:
        nonlocal import_count
        if depth > max_imports or import_count >= max_imports:
            return ""  # pragma: no cover
        try:
            content = file_read(path)
            sources.append(path)
        except Exception:
            return ""
        # 解析 @import 指令
        result_lines = []
        for line in content.splitlines():
            m = re.match(r"^@import\s+(.+)", line.strip())
            if m and import_count < max_imports:
                import_path = m.group(1).strip()
                if not Path(import_path).is_absolute():
                    import_path = str(Path(path).parent / import_path)  # pragma: no cover
                import_count += 1
                result_lines.append(read_with_imports(import_path, depth + 1))
            else:
                result_lines.append(line)
        return "\n".join(result_lines)

    for layer_path in layers:
        if layer_path:
            text = read_with_imports(layer_path)
            if text.strip():
                parts.append(text)

    return {
        "content": "\n\n".join(parts),
        "sources": sources,
        "import_count": import_count,
    }
