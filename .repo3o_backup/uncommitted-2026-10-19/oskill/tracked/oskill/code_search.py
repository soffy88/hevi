"""K-04 code_search — grep+glob composite file search.

Composes oprim:
    - glob_match
    - build_ripgrep_args + parse_ripgrep_output  (ripgrep IO via asyncio subprocess)
    - apply_gitignore
    - sort_by_mtime
    - parse_gitignore

IO-orchestration type. Not used as sub-call by sibling oskills.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

from oprim import (
    apply_gitignore,
    build_ripgrep_args,
    glob_match,  # noqa: F401
    parse_gitignore,
    parse_ripgrep_output,
    sort_by_mtime,
)
from oprim._hicode_types import FileEntry, Hit


async def code_search(
    root: Path,
    *,
    query: str,
    file_glob: str = "*",
) -> list[Hit]:
    """Search for query in files under root matching file_glob.

    Composes: glob_match, build_ripgrep_args, parse_ripgrep_output,
              parse_gitignore, apply_gitignore, sort_by_mtime.

    Args:
        root: Repository root directory.
        query: Search pattern (regex).
        file_glob: Glob restrict (default: all files).

    Returns:
        Hit list sorted by file mtime (newest first).

    Raises:
        ValueError: If query is empty.
        FileNotFoundError: If root does not exist.
    """
    if not query:
        raise ValueError("query must not be empty")
    if not root.exists():
        raise FileNotFoundError(f"root does not exist: {root}")

    # Build rg args — returns ["rg", "--json", ...pattern/glob...]; skip "rg" (index 0)
    args = build_ripgrep_args(
        pattern=query,
        glob=file_glob if file_glob != "*" else None,
    )

    # Run ripgrep
    raw_output = ""
    try:
        proc = await asyncio.create_subprocess_exec(
            "rg",
            *args[1:],  # args[0] == "rg", already the executable above
            str(root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        raw_output = stdout.decode("utf-8", errors="replace")
    except FileNotFoundError:
        return []  # rg not installed

    hits = parse_ripgrep_output(raw_output)

    # Apply gitignore filter
    gitignore_path = root / ".gitignore"
    if gitignore_path.exists():
        patterns = parse_gitignore(gitignore_path.read_text(encoding="utf-8"))
        hit_paths = [Path(h.path) for h in hits]
        allowed = {str(p) for p in apply_gitignore(hit_paths, patterns=patterns, root=root)}
        hits = [h for h in hits if h.path in allowed]

    # Sort by mtime using sort_by_mtime helper
    entries: list[FileEntry] = []
    for h in hits:
        p = Path(h.path)
        if not p.is_absolute():
            p = root / p
        try:
            mtime = p.stat().st_mtime
        except OSError:
            mtime = 0.0
        entries.append(FileEntry(path=Path(h.path), mtime=mtime))

    sorted_entries = sort_by_mtime(entries)
    path_order = {str(e.path): i for i, e in enumerate(sorted_entries)}
    hits.sort(key=lambda h: path_order.get(h.path, len(hits)))

    return cast(list[Hit], hits)
