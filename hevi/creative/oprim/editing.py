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


__all__ = ["PatchPreview", "TargetNotUnique", "apply_exact_edit", "preview_exact_edit"]
