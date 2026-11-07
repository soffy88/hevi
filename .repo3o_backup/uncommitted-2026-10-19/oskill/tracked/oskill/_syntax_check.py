"""Auto-split from hicode whl."""

from __future__ import annotations
from oprim import detect_language

import ast
import json
from typing import Any



def syntax_check(
    content: str,
    *,
    path: str = "",
    language: str | None = None,
) -> list[dict[str, Any]]:
    """对代码内容做语法检查，返回错误列表（纯内存）。

    组合：detect_language + 对应解析器（Python=ast，JSON=json.loads）。
    其他语言暂返回空列表（tree-sitter 接入点）。

    Args:
        content: 代码内容字符串。
        path: 文件路径（用于语言检测，可选）。
        language: 显式指定语言，覆盖 path 检测。

    Returns:
        错误 dict 列表，每项含 {line, message, severity}。
        空列表表示无错误。

    Example:
        >>> syntax_check("def f(\\n", path="x.py")
        [{"line": 1, "message": "unexpected EOF ...", "severity": 1}]
    """
    lang = language or (detect_language(path) if path else "unknown")
    errors: list[dict] = []

    if lang == "python":
        try:
            ast.parse(content)
        except SyntaxError as e:
            errors.append(
                {
                    "line": e.lineno or 1,
                    "message": str(e.msg),
                    "severity": 1,
                    "language": "python",
                }
            )
        except Exception as e:  # pragma: no cover
            errors.append(
                {"line": 1, "message": str(e), "severity": 1, "language": "python"}
            )  # pragma: no cover

    elif lang == "json":
        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            errors.append(
                {
                    "line": e.lineno,
                    "message": e.msg,
                    "severity": 1,
                    "language": "json",
                }
            )

    # 其他语言：暂无错误（tree-sitter 扩展点）
    return errors
