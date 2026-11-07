"""K-02 batch_edit — multi-edit with conflict detection and LSP validation.

Composes oprim:
    - plan_multiedit
    - detect_edit_conflict
    - apply_string_replace
    - compute_diff
    - (lsp_diagnostics via injected LspChecker, optional)

Stateless. No sibling oskill calls.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from oprim import apply_string_replace, compute_diff, detect_edit_conflict, plan_multiedit
from oprim._hicode_types import Edit

from ._hc_types import EditResult


class LspChecker(Protocol):
    async def diagnostics(self, path: Path) -> list[Any]: ...


async def batch_edit(
    original: str,
    *,
    edits: list[Edit],
    lsp: LspChecker | None = None,
) -> EditResult:
    """Apply multiple edits to *original*, checking for conflicts first.

    Composes: detect_edit_conflict, plan_multiedit, apply_string_replace, compute_diff.

    Args:
        original: Source text.
        edits: List of Edit(old, new) to apply in order.
        lsp: Optional LSP checker.

    Returns:
        EditResult with success, result, diff, conflicts noted in reason.
    """
    if not edits:
        return EditResult(success=True, result=original, diff="")

    conflicts = detect_edit_conflict(edits)
    if conflicts:
        desc = "; ".join(f"edits[{c.idx_a}] vs edits[{c.idx_b}]" for c in conflicts)
        return EditResult(
            success=False,
            result=original,
            reason=f"Conflicting edits: {desc}",
        )

    try:
        patches = plan_multiedit(original, edits=edits)
    except ValueError as exc:
        return EditResult(success=False, result=original, reason=str(exc))

    result = original
    for patch in patches:
        try:
            result = apply_string_replace(result, old=patch.old, new=patch.new)
        except ValueError as exc:
            return EditResult(success=False, result=original, reason=f"Edit failed: {exc}")

    diff = compute_diff(original, after=result)

    lsp_warnings: list[str] = []
    if lsp is not None:
        try:
            diags = await lsp.diagnostics(Path("<buffer>"))
            lsp_warnings = [str(d) for d in diags if getattr(d, "severity", 1) <= 1]
        except Exception as exc:
            lsp_warnings = [f"lsp error: {exc}"]

    return EditResult(success=True, result=result, diff=diff, lsp_warnings=lsp_warnings)
