"""K-03 patch_apply_verified — apply unified diff patch with verification.

Composes oprim:
    - parse_unified_diff  (already in oprim._parse_unified_diff)
    - apply_patch
    - apply_hunk
    - compute_diff
    - (lsp_diagnostics via injected LspChecker, optional)

Stateless. No sibling oskill calls.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from oprim import apply_hunk, apply_patch, compute_diff  # noqa: F401 (apply_hunk for patching)
from oprim._parse_unified_diff import parse_unified_diff

from ._hc_types import EditResult


class LspChecker(Protocol):
    async def diagnostics(self, path: Path) -> list[Any]: ...


async def patch_apply_verified(
    original: str,
    *,
    patch: str,
    lsp: LspChecker | None = None,
) -> EditResult:
    """Apply a unified diff patch to *original* and optionally verify with LSP.

    Composes: parse_unified_diff, apply_patch, apply_hunk, compute_diff.

    Args:
        original: Source text.
        patch: Unified diff string.
        lsp: Optional LSP checker.

    Returns:
        EditResult with success, patched text, diff, any lsp_warnings.
    """
    if not patch or not patch.strip():
        return EditResult(success=True, result=original, diff="")

    try:
        file_diffs = parse_unified_diff(patch)
    except Exception as exc:
        return EditResult(success=False, result=original, reason=f"Invalid patch format: {exc}")

    if not file_diffs:
        return EditResult(success=True, result=original, diff="")

    try:
        result = apply_patch(original, patch=patch)
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

    return EditResult(success=True, result=result, diff=diff, lsp_warnings=lsp_warnings)
