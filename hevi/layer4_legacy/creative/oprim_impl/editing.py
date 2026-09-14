"""Fail-closed targeted text editing."""

from __future__ import annotations

from dataclasses import dataclass


class TargetNotUnique(ValueError):
    """The requested edit does not identify exactly one location."""


@dataclass(frozen=True)
class PatchPreview:
    before: str
    after: str
    start: int
    end: int


@dataclass(frozen=True)
class SemanticLocator:
    """A bounded, explainable locator for a paragraph-level edit."""

    paragraph: int | None = None
    required_text: str | None = None


@dataclass(frozen=True)
class CascadeImpact:
    """References that require revalidation after a text patch."""

    changed_range: tuple[int, int]
    affected_refs: tuple[str, ...]


def preview_semantic_edit(
    text: str,
    locator: SemanticLocator,
    replacement: str,
    *,
    affected_refs: tuple[str, ...] = (),
) -> tuple[PatchPreview, CascadeImpact]:
    """Resolve a high-confidence paragraph locator without guessing.

    A locator must identify exactly one paragraph.  Free-form fuzzy matching is
    intentionally unsupported: ambiguous or missing locations fail closed.
    """

    paragraphs = text.split("\n\n")
    candidates = list(range(len(paragraphs)))
    if locator.paragraph is not None:
        candidates = [locator.paragraph] if 0 <= locator.paragraph < len(paragraphs) else []
    if locator.required_text is not None:
        candidates = [index for index in candidates if locator.required_text in paragraphs[index]]
    if len(candidates) != 1:
        raise TargetNotUnique(f"semantic locator resolved to {len(candidates)} paragraphs")
    index = candidates[0]
    paragraph = paragraphs[index]
    exact = preview_exact_edit(paragraph, paragraph, replacement)
    prefix = "\n\n".join(paragraphs[:index])
    offset = len(prefix) + (2 if index else 0)
    preview = PatchPreview(
        before=text,
        after=text[:offset] + exact.after + text[offset + len(paragraph) :],
        start=offset,
        end=offset + len(paragraph),
    )
    return preview, CascadeImpact((offset, offset + len(paragraph)), affected_refs)


def preview_exact_edit(text: str, target: str, replacement: str) -> PatchPreview:
    if not target:
        raise TargetNotUnique("empty target")
    count = text.count(target)
    if count != 1:
        raise TargetNotUnique(f"target occurs {count} times")
    start = text.index(target)
    end = start + len(target)
    return PatchPreview(text, text[:start] + replacement + text[end:], start, end)


def apply_exact_edit(text: str, preview: PatchPreview) -> str:
    if text != preview.before:
        raise TargetNotUnique("source changed after preview")
    return preview.after


__all__ = [
    "CascadeImpact",
    "PatchPreview",
    "SemanticLocator",
    "TargetNotUnique",
    "apply_exact_edit",
    "preview_exact_edit",
    "preview_semantic_edit",
]
