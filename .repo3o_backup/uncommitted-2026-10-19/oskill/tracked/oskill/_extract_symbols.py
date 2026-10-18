"""Auto-split from hicode whl."""

from __future__ import annotations
from oprim import detect_language, file_read

import ast
import re
from typing import Any


from ._types import Symbol


def extract_symbols(
    path: str,
    *,
    server: Any = None,  # LspServerHandle（可选）
    content: str | None = None,
) -> list[Symbol]:
    """从文件中提取代码符号列表（纯内存 + 可选 LSP）。

    无 LSP 时使用 AST（Python）或正则（其他语言）回退。

    Args:
        path: 文件路径。
        server: LspServerHandle（可选，有时用 LSP 获取精确符号）。
        content: 文件内容（可选，不提供则从 path 读）。

    Returns:
        Symbol 列表，按行号排序。

    Example:
        >>> syms = extract_symbols("x.py", content="def foo():\\n    pass\\n")
        >>> syms[0].name
        'foo'
    """
    if content is None:
        try:  # pragma: no cover
            content = file_read(path)  # pragma: no cover
        except Exception:  # pragma: no cover
            return []  # pragma: no cover

    lang = detect_language(path)
    symbols: list[Symbol] = []

    if lang == "python":
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    kind = "function"
                    sig = f"def {node.name}({_args_str(node.args)})"
                    doc = ast.get_docstring(node) or ""
                    symbols.append(
                        Symbol(
                            name=node.name,
                            kind=kind,
                            start_line=node.lineno,
                            end_line=getattr(node, "end_lineno", node.lineno),
                            path=path,
                            signature=sig,
                            docstring=doc[:120],
                        )
                    )
                elif isinstance(node, ast.ClassDef):
                    doc = ast.get_docstring(node) or ""
                    symbols.append(
                        Symbol(
                            name=node.name,
                            kind="class",
                            start_line=node.lineno,
                            end_line=getattr(node, "end_lineno", node.lineno),
                            path=path,
                            signature=f"class {node.name}",
                            docstring=doc[:120],
                        )
                    )
        except SyntaxError:
            pass
    else:
        # 正则回退：匹配常见函数/类定义
        for pat, kind in [
            (r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)", "function"),
            (r"^(?:export\s+)?class\s+(\w+)", "class"),
            (r"^def\s+(\w+)", "function"),
            (r"^class\s+(\w+)", "class"),
            (r"^(?:pub\s+)?fn\s+(\w+)", "function"),  # Rust
            (r"^func\s+(\w+)", "function"),  # Go
        ]:
            for i, line in enumerate(content.splitlines(), 1):
                m = re.match(pat, line.strip())
                if m:
                    symbols.append(
                        Symbol(
                            name=m.group(1),
                            kind=kind,
                            start_line=i,
                            end_line=i,
                            path=path,
                            signature=line.strip()[:80],
                        )
                    )

    return sorted(symbols, key=lambda s: s.start_line)


def _args_str(args: ast.arguments) -> str:
    parts = [a.arg for a in args.args]
    if args.vararg:
        parts.append(f"*{args.vararg.arg}")
    if args.kwarg:
        parts.append(f"**{args.kwarg.arg}")
    return ", ".join(parts)
