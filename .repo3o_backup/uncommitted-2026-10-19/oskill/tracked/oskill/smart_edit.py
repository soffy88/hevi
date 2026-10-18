"""K-01 smart_edit — precision string edit with optional LSP validation.

Composes oprim:
    - verify_unique_match
    - apply_string_replace
    - preserve_indentation
    - compute_diff
    - (lsp_diagnostics via injected LspChecker, optional)

Stateless. No sibling oskill calls.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Protocol

from oprim import (
    apply_string_replace,
    compute_diff,
    preserve_indentation,
    verify_unique_match,
)
from oprim._hicode_types import Hit

from ._hc_types import EditResult


class LspChecker(Protocol):
    async def diagnostics(self, path: Path) -> list[Any]: ...


def _parse_edit_from_instruction(instruction: str, original: str) -> tuple[str, str] | None:
    """Extract (old, new) from instruction if it follows SEARCH/REPLACE pattern."""
    # Pattern: <<<SEARCH\nold\n===\nnew\n>>>REPLACE
    m = re.search(r"<<<+\s*SEARCH\s*\n(.*?)\n=+\n(.*?)\n>>>+\s*REPLACE", instruction, re.DOTALL)
    if m:
        return m.group(1), m.group(2)
    return None


async def smart_edit(
    original: str,
    *,
    instruction: str,
    search_hits: list[Hit] | None = None,
    lsp: LspChecker | None = None,
) -> EditResult:
    """Apply a precise edit to *original* based on *instruction*.

    Args:
        original: Source text to edit.
        instruction: Edit instruction containing SEARCH/REPLACE markers.
        search_hits: Pre-fetched search hits to help locate target (injected by caller).
        lsp: Optional LSP checker for post-edit diagnostics.

    Returns:
        EditResult with success, result text, diff, and any lsp_warnings.
    """
    parsed = _parse_edit_from_instruction(instruction, original)
    if parsed is None:
        return EditResult(
            success=False,
            result=original,
            reason="Could not parse SEARCH/REPLACE blocks from instruction",
        )

    old, new = parsed

    if not verify_unique_match(original, target=old):
        # Try to use search_hits to narrow down
        if search_hits:
            # Use first hit line as context hint (best-effort; still need unique old)
            pass
        return EditResult(
            success=False,
            result=original,
            reason="Target not uniquely found in original (0 or >1 matches)",
        )

    new_aligned = preserve_indentation(old, new=new)
    try:
        result = apply_string_replace(original, old=old, new=new_aligned)
    except ValueError as exc:
        return EditResult(success=False, result=original, reason=str(exc))

    diff = compute_diff(original, after=result)

    lsp_warnings: list[str] = []
    if lsp is not None:
        try:
            diags = await lsp.diagnostics(Path("<buffer>"))
            lsp_warnings = [str(d) for d in diags if getattr(d, "severity", 1) <= 1]
        except Exception as exc:
            lsp_warnings = [f"lsp error: {exc}"]

    return EditResult(
        success=True,
        result=result,
        diff=diff,
        lsp_warnings=lsp_warnings,
    )
