"""Compatibility adapters into the canonical Production Graph."""

from .script2video import novel_plan_provenance, novel_plan_to_narrative
from .tongjian import (
    chapter_characters,
    chapter_to_narrative,
    legacy_provenance,
    source_document_from_text,
)

__all__ = [
    "chapter_characters",
    "chapter_to_narrative",
    "legacy_provenance",
    "novel_plan_provenance",
    "novel_plan_to_narrative",
    "source_document_from_text",
]
