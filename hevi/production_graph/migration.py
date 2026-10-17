"""Reversible adapter migration helpers.

Canonical writes happen first. Legacy projections are best-effort consumers;
their failure never rolls a committed canonical revision back.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


class MigrationProjectionError(RuntimeError):
    """The canonical write succeeded but a compatibility projection failed."""


def canonical_first_read[T](canonical: T | None, legacy_loader: Callable[[], T]) -> tuple[T, str]:
    """Dual-read helper: canonical data always wins when it exists."""

    if canonical is not None:
        return canonical, "canonical"
    return legacy_loader(), "legacy_fallback"


async def canonical_first_write[T](
    canonical_writer: Callable[[], Awaitable[T]],
    legacy_projector: Callable[[T], Awaitable[Any] | Any] | None = None,
) -> tuple[T, str | None]:
    """Commit canonical state, then project it for old readers."""

    canonical = await canonical_writer()
    if legacy_projector is None:
        return canonical, None
    try:
        projected = legacy_projector(canonical)
        if hasattr(projected, "__await__"):
            await projected
    except Exception as exc:
        raise MigrationProjectionError(
            "canonical write committed; legacy projection failed"
        ) from exc
    return canonical, "projected"


__all__ = ["MigrationProjectionError", "canonical_first_read", "canonical_first_write"]
