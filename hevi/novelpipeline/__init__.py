"""File-based long-form serial novel pipeline (hevi.novelpipeline).

Clean-room original implementation: brief → book.json, per-chapter writing
with generation-side word-count governance, and an import-and-continue
workflow.  See :mod:`hevi.novelpipeline.core` for the full design.
"""

from __future__ import annotations

from hevi.novelpipeline.core import (
    DEFAULT_GOVERNANCE_DELTA,
    LlmFn,
    char_count,
    continue_work,
    create_novel,
    load_book,
    save_book,
    split_imported_text,
    verify_book,
    write_chapter,
)

__all__ = [
    "DEFAULT_GOVERNANCE_DELTA",
    "LlmFn",
    "char_count",
    "continue_work",
    "create_novel",
    "load_book",
    "save_book",
    "split_imported_text",
    "verify_book",
    "write_chapter",
]
