"""Auto-split from hicode whl."""

from __future__ import annotations
from oprim import detect_language, count_tokens

import re


from ._types import Chunk


def chunk_code(
    content: str,
    *,
    path: str = "",
    language: str | None = None,
    max_tokens: int = 500,
    model: str = "claude-sonnet-4-6",
) -> list[Chunk]:
    """将代码内容按语义边界分块（纯内存）。

    组合：detect_language + 语义切分（Python=函数/类级，其他=行数）。

    Args:
        content: 代码内容。
        path: 文件路径（用于语言检测）。
        language: 显式语言。
        max_tokens: 每块最大 token 数（粗估）。
        model: 用于 count_tokens 的模型名。

    Returns:
        Chunk 列表（按代码结构切分）。

    Example:
        >>> chunks = chunk_code("def f():\\n    pass\\ndef g():\\n    pass\\n", path="x.py")
        >>> len(chunks) >= 1
        True
    """
    lang = language or (detect_language(path) if path else "unknown")
    lines = content.splitlines(keepends=True)
    chunks: list[Chunk] = []

    if lang == "python":
        # 按顶级函数/类边界切分
        boundaries = [0]
        for i, line in enumerate(lines):
            if re.match(r"^(def |class |async def )", line):
                if i > 0:
                    boundaries.append(i)
        boundaries.append(len(lines))

        for i in range(len(boundaries) - 1):
            start, end = boundaries[i], boundaries[i + 1]
            chunk_lines = lines[start:end]
            chunk_text = "".join(chunk_lines)
            # 若块太大，进一步按行数切
            if count_tokens(chunk_text, model=model) > max_tokens:
                step = max(1, max_tokens * 4 // 80)  # ~80 chars/line
                for j in range(0, len(chunk_lines), step):
                    sub = "".join(chunk_lines[j : j + step])
                    if sub.strip():
                        chunks.append(
                            Chunk(
                                content=sub,
                                start_line=start + j,
                                end_line=min(start + j + step, end),
                                token_count=count_tokens(sub, model=model),
                                path=path,
                                language=lang,
                                chunk_id=f"{path}:{start + j}",
                            )
                        )
            else:
                if chunk_text.strip():
                    chunks.append(
                        Chunk(
                            content=chunk_text,
                            start_line=start,
                            end_line=end,
                            token_count=count_tokens(chunk_text, model=model),
                            path=path,
                            language=lang,
                            chunk_id=f"{path}:{start}",
                        )
                    )
    else:
        # 通用：按 max_tokens 行数切
        step = max(1, max_tokens * 4 // 80)
        for i in range(0, len(lines), step):
            sub = "".join(lines[i : i + step])
            if sub.strip():
                chunks.append(
                    Chunk(
                        content=sub,
                        start_line=i,
                        end_line=min(i + step, len(lines)),
                        token_count=count_tokens(sub, model=model),
                        path=path,
                        language=lang,
                        chunk_id=f"{path}:{i}",
                    )
                )

    return chunks
