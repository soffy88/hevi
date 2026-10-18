"""K-10 code_intel_lookup — LSP-powered code intelligence context lookup.

Composes oprim:
    - lsp_hover
    - lsp_find_references
    - lsp_goto_definition
    - diagnostics_to_summary
    - location_to_snippet

IO-orchestration (LSP calls). Concurrent via asyncio.gather.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Protocol

from oprim import (
    diagnostics_to_summary,  # noqa: F401
    location_to_snippet,
    lsp_find_references,
    lsp_goto_definition,
    lsp_hover,
)

from ._hc_types import IntelResult, Pos


class LspConnection(Protocol):
    async def request(self, method: str, params: dict[str, Any]) -> Any: ...


async def code_intel_lookup(
    path: Path,
    *,
    pos: Pos,
    lsp: LspConnection,
) -> IntelResult:
    """Gather code intelligence context at a source position via LSP.

    Composes: lsp_hover, lsp_find_references, lsp_goto_definition,
              diagnostics_to_summary, location_to_snippet.

    Args:
        path: Source file path.
        pos: Cursor position (line, character).
        lsp: Injected LSP connection.

    Returns:
        IntelResult with hover_text, definition location, references_count, snippet.
    """
    lsp_pos = {"line": pos.line, "character": pos.character}

    # Concurrent LSP calls
    hover_task = lsp_hover(path, pos=lsp_pos, lsp=lsp)
    refs_task = lsp_find_references(path, pos=lsp_pos, lsp=lsp)
    def_task = lsp_goto_definition(path, pos=lsp_pos, lsp=lsp)

    gathered: list[Any] = list(
        await asyncio.gather(hover_task, refs_task, def_task, return_exceptions=True)
    )
    hover_raw: Any = gathered[0]
    refs_raw: Any = gathered[1]
    def_raw: Any = gathered[2]

    hover_text = ""
    if isinstance(hover_raw, dict):
        hover_text = hover_raw.get("contents", {}).get("value", "") or str(
            hover_raw.get("contents", "")
        )
    elif isinstance(hover_raw, str):
        hover_text = hover_raw

    references_count = 0
    if isinstance(refs_raw, list):
        references_count = len(refs_raw)

    definition = ""
    snippet = ""
    if isinstance(def_raw, dict):
        uri = def_raw.get("uri", "")
        rng = def_raw.get("range", {})
        start = rng.get("start", {})
        definition = f"{uri}:{start.get('line', 0)}:{start.get('character', 0)}"
        try:
            snippet_raw = await location_to_snippet(def_raw, lsp=lsp)
            snippet = str(snippet_raw) if snippet_raw else ""
        except Exception:
            snippet = ""
    elif isinstance(def_raw, list) and def_raw:
        first = def_raw[0]
        if isinstance(first, dict):
            uri = first.get("uri", "")
            rng = first.get("range", {})
            start = rng.get("start", {})
            definition = f"{uri}:{start.get('line', 0)}"

    return IntelResult(
        hover_text=hover_text,
        definition=definition,
        references_count=references_count,
        snippet=snippet,
    )
