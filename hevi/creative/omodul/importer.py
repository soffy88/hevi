"""Existing-work import and continuation foundations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from hevi.obase.creative import CreativeAuthority, CreativeSource, NarrativeCanon, NarrativeProject


@dataclass(frozen=True)
class ImportResult:
    project: NarrativeProject
    canon: NarrativeCanon
    source: CreativeSource
    chapters: tuple[str, ...]
    unresolved: tuple[str, ...]


class ImportModule:
    """Reconstruct a project envelope instead of dumping a manuscript into context."""

    _heading = re.compile(r"^#{1,3}\s+.+$", re.MULTILINE)

    def import_text(
        self,
        *,
        title: str,
        text: str,
        language: str = "en",
        project_id: UUID | None = None,
    ) -> ImportResult:
        if not text.strip():
            raise ValueError("IMPORT_EMPTY_SOURCE")
        pid = project_id or uuid4()
        source = CreativeSource(
            project_id=pid,
            title=title,
            source_type="UPLOADED",
            authority=CreativeAuthority.EVIDENCE,
        )
        canon = NarrativeCanon(project_id=pid)
        project = NarrativeProject(
            project_id=pid,
            title=title,
            language=language,
            narrative_kind="NOVEL",
            canon_id=canon.object_id,
        )
        chapters = self._split_chapters(text)
        unresolved = ("character roster requires review", "timeline requires review")
        return ImportResult(project, canon, source, chapters, unresolved)

    def import_path(
        self,
        path: str | Path,
        *,
        title: str | None = None,
        language: str = "en",
        project_id: UUID | None = None,
    ) -> ImportResult:
        source = Path(path)
        if not source.is_file():
            raise FileNotFoundError(source)
        return self.import_text(
            title=title or source.stem,
            text=source.read_text(encoding="utf-8"),
            language=language,
            project_id=project_id,
        )

    def _split_chapters(self, text: str) -> tuple[str, ...]:
        matches = list(self._heading.finditer(text))
        if not matches:
            return (text.strip(),)
        chapters: list[str] = []
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            body = text[match.end() : end].strip()
            if body:
                chapters.append(body)
        return tuple(chapters)


__all__ = ["ImportModule", "ImportResult"]
