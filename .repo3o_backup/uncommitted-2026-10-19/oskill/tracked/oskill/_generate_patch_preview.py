"""Auto-split from hicode whl."""

from __future__ import annotations
from oprim import compute_diff



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
