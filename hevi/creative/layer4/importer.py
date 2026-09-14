"""Existing-work import, canonical reconstruction, and continuation foundations."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from hevi.obase.creative import (
    ChapterSummary,
    Character,
    CreativeArtifact,
    CreativeAuthority,
    CreativeSource,
    NarrativeCanon,
    NarrativeObservation,
    NarrativeProject,
    ObservationFact,
    PendingHook,
    ProvenanceRef,
    TimelineState,
    WorldRule,
)

# Words that never identify an entity on their own.  Kept small and
# English-focused because the qualification corpus is English; extraction stays
# deterministic and transparent rather than statistical.
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "book",
        "but",
        "by",
        "chapter",
        "chapters",
        "did",
        "do",
        "does",
        "doing",
        "epilogue",
        "for",
        "from",
        "had",
        "has",
        "have",
        "he",
        "her",
        "hers",
        "him",
        "his",
        "in",
        "into",
        "is",
        "it",
        "its",
        "nor",
        "note",
        "notes",
        "of",
        "on",
        "onto",
        "or",
        "part",
        "prologue",
        "record",
        "records",
        "said",
        "says",
        "she",
        "story",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "to",
        "was",
        "were",
        "with",
        "yet",
    }
)


@dataclass(frozen=True)
class ImportResult:
    project: NarrativeProject
    canon: NarrativeCanon
    source: CreativeSource
    chapters: tuple[str, ...]
    unresolved: tuple[str, ...]


@dataclass(frozen=True)
class ReconstructedState:
    """Canon state reconstructed from an imported manuscript."""

    canon: NarrativeCanon
    characters: tuple[Character, ...]
    world_rules: tuple[WorldRule, ...]
    timeline: TimelineState
    hooks: tuple[PendingHook, ...]
    summaries: tuple[ChapterSummary, ...]


class ImportModule:
    """Reconstruct a project envelope instead of dumping a manuscript into context."""

    _heading = re.compile(r"^#{1,3}\s+.+$", re.MULTILINE)
    _character = re.compile(r"\b[A-Z][a-z]{2,}\b")
    _word = re.compile(r"[a-z]+")

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

    def reconstruct(self, result: ImportResult) -> ReconstructedState:
        """Deterministically reconstruct canon state from imported chapters.

        The runtime, not the caller, owns the extraction.  Characters come from
        proper nouns, world rules from repeated non-stopword bigrams, the
        timeline from chapter order, and one open hook marks where continuation
        resumes.
        """

        if not result.chapters:
            raise ValueError("RECONSTRUCTION_EMPTY_SOURCE")
        project_id = result.project.project_id
        characters = self._extract_characters(project_id, result.chapters)
        world_rules = self._extract_world_rules(project_id, result.chapters, characters)
        timeline = TimelineState(
            project_id=project_id,
            current_marker=f"chapter-{len(result.chapters)}",
            authority=CreativeAuthority.EVIDENCE,
        )
        hooks = (
            PendingHook(
                project_id=project_id,
                description=f"resolve the open thread after chapter {len(result.chapters)}",
                priority="HIGH",
                authority=CreativeAuthority.EVIDENCE,
            ),
        )
        summaries = tuple(
            ChapterSummary(
                project_id=project_id,
                chapter_id=self._chapter_id(project_id, index),
                summary=self._first_sentence(chapter),
                character_ids=tuple(character.object_id for character in characters),
                authority=CreativeAuthority.EVIDENCE,
            )
            for index, chapter in enumerate(result.chapters, start=1)
        )
        canon = result.canon.model_copy(
            update={
                "character_ids": tuple(character.object_id for character in characters),
                "world_rule_ids": tuple(rule.object_id for rule in world_rules),
                "timeline_state_id": timeline.object_id,
                "hook_ids": tuple(hook.object_id for hook in hooks),
                "revision": result.canon.revision + 1,
            }
        )
        return ReconstructedState(canon, characters, world_rules, timeline, hooks, summaries)

    def draft_continuation(
        self,
        result: ImportResult,
        state: ReconstructedState,
        *,
        count: int = 3,
    ) -> tuple[str, ...]:
        """Draft a bounded continuation bound to the reconstructed canon."""

        if count < 1:
            raise ValueError("CONTINUATION_COUNT_INVALID")
        start = len(result.chapters)
        lead = state.characters[0].name if state.characters else "the narrator"
        return tuple(
            f"{lead} continues the account in chapter {start + offset}."
            for offset in range(1, count + 1)
        )

    def continuation_observation(
        self,
        state: ReconstructedState,
        *,
        chapters: tuple[str, ...],
        artifact: CreativeArtifact,
    ) -> NarrativeObservation:
        """Project the drafted continuation as a settleable observation."""

        if not chapters:
            raise ValueError("CONTINUATION_EMPTY")
        provenance = artifact.provenance or (
            ProvenanceRef(ref_id=str(artifact.object_id), ref_type="CONTINUATION"),
        )
        source_ref = provenance[0]
        facts = tuple(
            ObservationFact(
                fact_type="TIME",
                statement=chapter,
                source_ref=source_ref,
                confidence=0.6,
            )
            for chapter in chapters
        )
        return NarrativeObservation(
            project_id=state.canon.project_id,
            artifact_id=artifact.object_id,
            canon_revision=state.canon.revision,
            facts=facts,
            extractor="import-continuation",
            authority=CreativeAuthority.PROJECTION,
        )

    def _extract_characters(
        self, project_id: UUID, chapters: tuple[str, ...]
    ) -> tuple[Character, ...]:
        counts: Counter[str] = Counter()
        first_seen: dict[str, int] = {}
        for index, chapter in enumerate(chapters):
            for token in self._character.findall(chapter):
                key = token.lower()
                if key in _STOPWORDS:
                    continue
                counts[token] += 1
                first_seen.setdefault(token, index)
        ordered = sorted(counts, key=lambda name: (first_seen[name], name))
        return tuple(
            Character(project_id=project_id, name=name, authority=CreativeAuthority.EVIDENCE)
            for name in ordered
            if counts[name] >= 2
        )

    def _extract_world_rules(
        self,
        project_id: UUID,
        chapters: tuple[str, ...],
        characters: tuple[Character, ...],
    ) -> tuple[WorldRule, ...]:
        excluded = {character.name.lower() for character in characters}
        frequency: Counter[tuple[str, str]] = Counter()
        for chapter in chapters:
            words = self._word.findall(chapter.lower())
            seen: set[tuple[str, str]] = set()
            for left, right in pairwise(words):
                if left in _STOPWORDS or right in _STOPWORDS:
                    continue
                if left in excluded or right in excluded:
                    continue
                seen.add((left, right))
            for bigram in seen:
                frequency[bigram] += 1
        if not frequency:
            return ()
        best = max(
            sorted(frequency),
            key=lambda bigram: (frequency[bigram], sum(len(word) for word in bigram)),
        )
        return (
            WorldRule(
                project_id=project_id,
                statement=" ".join(best),
                authority=CreativeAuthority.EVIDENCE,
            ),
        )

    def _chapter_id(self, project_id: UUID, index: int) -> UUID:
        return uuid5(NAMESPACE_URL, f"{project_id}:chapter:{index}")

    @staticmethod
    def _first_sentence(text: str) -> str:
        stripped = text.strip()
        for terminator in (". ", "! ", "? "):
            position = stripped.find(terminator)
            if position != -1:
                return stripped[: position + 1]
        return stripped

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


__all__ = ["ImportModule", "ImportResult", "ReconstructedState"]
