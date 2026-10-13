"""Unified FX template data model and registry.

Registry collects templates from multiple sources (talkcraft, xfade, sfx)
into a single, queryable catalog with consistent schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Preview asset locations (shared by the API router and scripts/fx_preview.py)
# ---------------------------------------------------------------------------

#: Repo-relative directory holding rendered previews.
PREVIEW_REL_DIR = "output/fx_previews"


def repo_root() -> Path:
    """Repository root (3 parents above hevi/fx/registry.py)."""
    return Path(__file__).resolve().parents[2]


def template_slug(template_id: str) -> str:
    """Filesystem-safe slug for a template's preview assets.

    ``tc:focus-dim-spotlight`` -> ``tc__focus-dim-spotlight``
    """
    return template_id.replace(":", "__")


def preview_mp4_path(template_id: str) -> Path:
    """Absolute path of a template's preview MP4 (may not exist)."""
    return repo_root() / PREVIEW_REL_DIR / f"{template_slug(template_id)}.mp4"


def preview_thumbnail_path(template_id: str) -> Path:
    """Absolute path of a template's thumbnail JPG (may not exist)."""
    return repo_root() / PREVIEW_REL_DIR / f"{template_slug(template_id)}.jpg"


class Category(StrEnum):
    """FX template category — maps 7 talkcraft categories + sources to 4 targets."""

    TRANSITION = "transition"
    CHARACTER = "character"
    STYLE = "style"
    OVERLAY = "overlay"


class Source(StrEnum):
    """FX template source origin."""

    TALKCRAFT = "talkcraft"
    XFADE = "xfade"
    SFX = "sfx"
    CUSTOM = "custom"


@dataclass(slots=True)
class FXTemplate:
    """Single FX template entry in the unified registry.

    Attributes:
        id: Unique template identifier (source-qualified).
        name_zh: Human-readable Chinese name.
        category: One of transition | character | style | overlay.
        source: Origin system (talkcraft | xfade | sfx | custom).
        source_ref: Reference back to source system (e.g. tplMeta id, xfade name, file path).
        tags: Free-form tags for search/filtering.
        duration_hint: Suggested duration in seconds (or None if unknown).
        preview_mp4: Relative path to preview MP4 (or None if not rendered).
        thumbnail: Relative path to thumbnail JPG (or None if not rendered).
    """

    id: str
    name_zh: str
    category: Category
    source: Source
    source_ref: str | None = None
    tags: list[str] = field(default_factory=list)
    duration_hint: float | None = None
    preview_mp4: str | None = None
    thumbnail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-safe dict for API responses."""
        return {
            "id": self.id,
            "name_zh": self.name_zh,
            "category": self.category.value,
            "source": self.source.value,
            "source_ref": self.source_ref,
            "tags": list(self.tags),
            "duration_hint": self.duration_hint,
            "preview_mp4": self.preview_mp4,
            "thumbnail": self.thumbnail,
        }


class FXRegistry:
    """In-memory registry of all FX templates.

    Loads templates from multiple sources and provides filtering,
    searching, and lookup capabilities.
    """

    def __init__(self) -> None:
        self._templates: dict[str, FXTemplate] = {}

    def add(self, template: FXTemplate) -> None:
        """Add a template to the registry. Raises ValueError on duplicate id."""
        if template.id in self._templates:
            raise ValueError(f"Duplicate FX template id: {template.id}")
        self._templates[template.id] = template

    def add_many(self, templates: list[FXTemplate]) -> None:
        """Add multiple templates at once."""
        for t in templates:
            self.add(t)

    def get(self, template_id: str) -> FXTemplate | None:
        """Get a template by id. Returns None if not found."""
        return self._templates.get(template_id)

    def list_all(self) -> list[FXTemplate]:
        """Return all templates (unordered)."""
        return list(self._templates.values())

    def filter(
        self,
        *,
        category: Category | str | None = None,
        source: Source | str | None = None,
        q: str | None = None,
    ) -> list[FXTemplate]:
        """Filter templates by category, source, and/or search query.

        Args:
            category: Filter by category (exact match).
            source: Filter by source (exact match).
            q: Case-insensitive substring search on id, name_zh, tags.
        """
        results = list(self._templates.values())

        if category is not None:
            cat = Category(category) if isinstance(category, str) else category
            results = [t for t in results if t.category == cat]

        if source is not None:
            src = Source(source) if isinstance(source, str) else source
            results = [t for t in results if t.source == src]

        if q is not None:
            q_lower = q.lower()
            results = [
                t
                for t in results
                if q_lower in t.id.lower()
                or q_lower in t.name_zh.lower()
                or any(q_lower in tag.lower() for tag in t.tags)
            ]

        return results

    def count(self) -> int:
        """Total number of templates."""
        return len(self._templates)

    def categories(self) -> dict[str, int]:
        """Count templates per category."""
        counts: dict[str, int] = {}
        for t in self._templates.values():
            key = t.category.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    def sources(self) -> dict[str, int]:
        """Count templates per source."""
        counts: dict[str, int] = {}
        for t in self._templates.values():
            key = t.source.value
            counts[key] = counts.get(key, 0) + 1
        return counts