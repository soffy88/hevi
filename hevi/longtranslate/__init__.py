"""Long-text translation line: chunked translation + glossary QA.

Clean-room implementation (original design). The public surface is
:func:`hevi.longtranslate.core.translate_long`.
"""

from hevi.longtranslate.core import (
    LongTranslateError,
    check_glossary,
    split_into_chunks,
    translate_long,
)

__all__ = [
    "LongTranslateError",
    "check_glossary",
    "split_into_chunks",
    "translate_long",
]
