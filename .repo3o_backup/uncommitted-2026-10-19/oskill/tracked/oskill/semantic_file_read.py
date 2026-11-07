"""K-05 semantic_file_read — intelligent file read with encoding and focus.

Composes oprim:
    - file_read
    - detect_encoding
    - detect_mime
    - is_binary
    - truncate_for_context
    - add_line_numbers

IO-orchestration type (file_read does disk I/O).
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from oprim import (
    add_line_numbers,
    detect_encoding,
    detect_mime,
    file_read,  # noqa: F401
    is_binary,
    truncate_for_context,
)


def semantic_file_read(
    path: Path,
    *,
    focus: str | None = None,
    max_lines: int = 2000,
) -> str:
    """Read a file intelligently: encoding detection, binary guard, truncation, line numbers.

    Composes: file_read, detect_encoding, detect_mime, is_binary,
              truncate_for_context, add_line_numbers.

    Args:
        path: File path to read.
        focus: Optional keyword to scroll to relevant section.
        max_lines: Maximum lines to return (default 2000).

    Returns:
        File content with line numbers, or binary notice.

    Raises:
        FileNotFoundError: If path does not exist.
    """
    p = Path(path)

    # Read raw bytes for binary/encoding detection
    raw = p.read_bytes()

    # Binary check
    if is_binary(raw):
        return f"(binary file, {len(raw)} bytes, mime={detect_mime(p)})"

    # Encoding detection and decode
    encoding = detect_encoding(raw)
    try:
        content = raw.decode(encoding, errors="replace")
    except Exception:
        content = raw.decode("utf-8", errors="replace")

    # Truncate
    content = truncate_for_context(content, max_lines=max_lines, max_bytes=100_000)

    # Focus: find region containing focus keyword
    if focus:
        lines = content.splitlines(keepends=True)
        focus_lower = focus.lower()
        focus_indices = [i for i, line in enumerate(lines) if focus_lower in line.lower()]
        if focus_indices:
            # Show window around first hit
            center = focus_indices[0]
            start = max(0, center - 20)
            end = min(len(lines), center + 80)
            content = "".join(lines[start:end])
        # else: return head (already truncated)

    # Add line numbers
    return cast(str, add_line_numbers(content))
