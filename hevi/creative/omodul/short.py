"""Short-fiction production package."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from hevi.obase.creative import CoverBrief, NarrativeProject


@dataclass(frozen=True)
class SalesPackage:
    synopsis: str
    selling_points: tuple[str, ...]
    cover_brief: CoverBrief


@dataclass(frozen=True)
class ShortProduction:
    project: NarrativeProject
    outline: tuple[str, ...]
    manuscript: tuple[str, ...]
    sales_package: SalesPackage


class ShortFictionModule:
    def create(
        self,
        *,
        project_id: UUID,
        title: str,
        direction: str,
        genre: str,
        chapter_count: int,
        length: int,
        language: str,
        materials: tuple[str, ...] = (),
    ) -> ShortProduction:
        if chapter_count < 1 or length < chapter_count:
            raise ValueError("SHORT_INVALID_LENGTH")
        if not direction.strip() or not genre.strip():
            raise ValueError("SHORT_MISSING_BRIEF")
        outline = tuple(f"Chapter {index}: {direction}" for index in range(1, chapter_count + 1))
        manuscript = tuple(f"{item}\n\n{direction}" for item in outline)
        brief = CoverBrief(
            project_id=project_id,
            title=title,
            visual_concept=f"abstract {genre} cover for {title}",
            palette=(),
            negative_constraints=("do not copy a reference work",),
        )
        package = SalesPackage(
            synopsis=f"{direction} ({genre})",
            selling_points=tuple(materials) or (genre, direction),
            cover_brief=brief,
        )
        project = NarrativeProject(
            project_id=project_id,
            title=title,
            language=language,
            narrative_kind="SHORT",
        )
        return ShortProduction(project, outline, manuscript, package)


__all__ = ["SalesPackage", "ShortFictionModule", "ShortProduction"]
