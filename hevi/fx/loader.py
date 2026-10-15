"""FX registry loader — aggregates all sources into a single registry.

Usage:
    from hevi.fx.loader import load_all
    registry = load_all()
    templates = registry.filter(category="transition")
"""

from __future__ import annotations

import logging

from hevi.fx.registry import FXRegistry, preview_mp4_path, preview_thumbnail_path
from hevi.fx.sources import (
    load_sfx,
    load_talkcraft_with_skipped,
    load_xfade,
)

logger = logging.getLogger(__name__)


def load_all(*, sync_previews: bool = True) -> FXRegistry:
    """Create and populate a registry with all FX templates.

    Loads templates from:
    - talkcraft (``hevi-remotion-talkcraft/src/cards/tplMeta.ts``, read-only)
    - xfade (``hevi.assembly.xfade_transitions`` if importable, else ffmpeg help)
    - sfx (``assets/audio/sfx/library/manifest.json`` if present, else *.wav scan)

    Entries skipped by a source (e.g. a talkcraft card whose category is not in
    the map) are recorded on the registry as ``registry.skipped`` — never
    silently dropped.

    Args:
        sync_previews: If True (default), fill ``preview_mp4`` / ``thumbnail``
            for any template whose rendered preview already exists on disk.
            ``scripts/fx_preview.py`` writes those files; this keeps the registry
            honest about what is actually available.

    Returns:
        A fully populated FXRegistry instance.
    """
    registry = FXRegistry()

    try:
        talkcraft, skipped = load_talkcraft_with_skipped()
        registry.add_many(talkcraft)
        registry.skipped["talkcraft"] = skipped
    except Exception as e:  # noqa: BLE001 — a broken source must not kill the catalog
        logger.warning("failed to load talkcraft templates: %s", e)
        registry.load_errors["talkcraft"] = str(e)

    for name, loader in (("xfade", load_xfade), ("sfx", load_sfx)):
        try:
            registry.add_many(loader())
        except Exception as e:  # noqa: BLE001 — a broken source must not kill the catalog
            logger.warning("failed to load %s templates: %s", name, e)
            registry.load_errors[name] = str(e)

    if sync_previews:
        sync_previews_disk(registry)

    return registry


def sync_previews_disk(registry: FXRegistry) -> int:
    """Attach on-disk preview paths to templates that have them rendered.

    Returns:
        Number of templates whose preview files were found.
    """
    found = 0
    for t in registry.list_all():
        mp4 = preview_mp4_path(t.id)
        jpg = preview_thumbnail_path(t.id)
        if mp4.exists():
            t.preview_mp4 = f"{mp4.relative_to(registry_repo_root())}"
        if jpg.exists():
            t.thumbnail = f"{jpg.relative_to(registry_repo_root())}"
        if t.preview_mp4 or t.thumbnail:
            found += 1
    return found


def registry_repo_root():  # noqa: ANN202 — re-export for relative_path arithmetic
    from hevi.fx.registry import repo_root

    return repo_root()


# Module-level singleton for convenience
_registry: FXRegistry | None = None


def get_registry() -> FXRegistry:
    """Get the global registry singleton (lazy-loaded)."""
    global _registry
    if _registry is None:
        _registry = load_all()
    return _registry


def reset_registry() -> None:
    """Reset the global registry (useful for testing)."""
    global _registry
    _registry = None
