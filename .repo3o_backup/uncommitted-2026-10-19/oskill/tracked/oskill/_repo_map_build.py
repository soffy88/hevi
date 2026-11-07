"""Auto-split from hicode whl."""

from __future__ import annotations
from oskill import extract_symbols
from oprim import detect_language, file_read, glob_match

from pathlib import Path



from ._types import RepoFile, RepoMap


def repo_map_build(
    *,
    root: str,
    ignore: list[str] | None = None,
    max_files: int = 500,
    head_lines: int = 5,
) -> RepoMap:
    """构建代码库结构地图（文件遍历 + 符号提取）。

    组合：glob_match + file_read（头部）+ extract_symbols。
    oskill 约束：只读，不写盘。

    Args:
        root: 仓库根目录。
        ignore: 额外 glob 忽略模式列表。
        max_files: 最多处理文件数，默认 500。
        head_lines: 每个文件读取头部行数，默认 5。

    Returns:
        RepoMap（含文件列表、语言统计）。

    Example:
        >>> rmap = repo_map_build(root="/project")
        >>> rmap.total_files > 0
        True
    """
    _IGNORE = {
        ".git",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
        ".mypy_cache",
        ".ruff_cache",
    }
    _EXTS = {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".c",
        ".cpp",
        ".cs",
        ".rb",
    }

    extra_ignore = set(ignore or [])
    files: list[RepoFile] = []
    languages: dict[str, int] = {}

    try:
        all_paths = glob_match("**/*", root=root, respect_gitignore=True)
    except Exception:
        return RepoMap(root=root, files=[], total_files=0, languages={})

    for p in all_paths[: max_files * 2]:  # 多取再过滤
        if len(files) >= max_files:
            break

        # 过滤目录和忽略项
        if not p.is_file():
            continue  # pragma: no cover
        rel = str(p.relative_to(root) if hasattr(p, "relative_to") else p)
        parts = Path(rel).parts
        if any(part in _IGNORE or part in extra_ignore for part in parts):
            continue  # pragma: no cover
        if p.suffix not in _EXTS:
            continue  # pragma: no cover

        lang = detect_language(str(p))
        languages[lang] = languages.get(lang, 0) + 1

        try:
            size = p.stat().st_size
            raw = file_read(str(p))
            head = "\n".join(raw.splitlines()[:head_lines])
            syms = extract_symbols(str(p), content=raw)
        except Exception:  # pragma: no cover
            head = ""  # pragma: no cover
            syms = []  # pragma: no cover
            size = 0  # pragma: no cover

        files.append(
            RepoFile(
                path=str(p),
                language=lang,
                size_bytes=size,
                symbols=syms,
                head_lines=head,
            )
        )

    return RepoMap(root=root, files=files, total_files=len(files), languages=languages)
