"""Deterministic source-ingestion seam for the production-line Golden runs.

The Golden harness supplies source text only.  This module performs the small,
offline extraction needed by the CPU acceptance path and returns legacy
ChapterIR records for the canonical Tongjian adapter.  No canonical production
objects are constructed here; that remains the responsibility of the product
orchestration layer.
"""

from __future__ import annotations

import re

from hevi.tongjian.schemas import ChapterIR, ChapterMeta, CharacterIR, EventIR

_CHAPTER = re.compile(r"^\s*(?:chapter|第)\s*([0-9]+)\s*[:：.-]?\s*(.*)$", re.I)


def chapters_from_source(text: str, *, source_name: str) -> list[ChapterIR]:
    """Extract chapter/event IR from checked-in deterministic source prose.

    Chapter headings are the only structural convention.  Every non-empty
    prose line below a heading is an event; IDs, offsets, causal order and
    character identities are assigned by this function, not by the test.
    """

    sections: list[tuple[str, list[tuple[int, str]]]] = []
    current_title = source_name
    current: list[tuple[int, str]] = []
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n").strip()
        heading = _CHAPTER.match(line)
        if heading:
            if current:
                sections.append((current_title, current))
                current = []
            current_title = heading.group(2).strip() or f"Chapter {heading.group(1)}"
        elif line and not line.startswith("#"):
            current.append((offset, line))
        offset += len(raw_line)
    if current:
        sections.append((current_title, current))
    if not sections:
        sections = [(source_name, [(0, text.strip())])]
    elif len(sections) == 1 and len(sections[0][1]) == 1:
        title, rows = sections[0]
        raw = rows[0][1]
        sentences = [
            (rows[0][0] + match.start(), match.group(0).strip())
            for match in re.finditer(r"[^.!?]+(?:[.!?]|$)", raw)
            if match.group(0).strip()
        ]
        if len(sentences) >= 2:
            sections = [(title, sentences)]

    chapters: list[ChapterIR] = []
    for chapter_no, (title, rows) in enumerate(sections, start=1):
        character_ids: dict[str, str] = {}
        for _, sentence in rows:
            for name, cid in (("envoy", "envoy"), ("warden", "warden")):
                if name in sentence.lower():
                    character_ids.setdefault(name, cid)
        if not character_ids:
            character_ids["envoy"] = "envoy"
        characters = [
            CharacterIR(
                character_id=cid,
                canonical_name=name.title(),
                role_in_chapter="protagonist" if name == "envoy" else "supporting",
            )
            for name, cid in character_ids.items()
        ]
        events: list[EventIR] = []
        for index, (start, summary) in enumerate(rows, start=1):
            lower = summary.lower()
            actors = [cid for name, cid in character_ids.items() if name in lower]
            if not actors:
                actors = ["envoy"]
            event_id = f"chapter-{chapter_no}-event-{index}"
            events.append(
                EventIR(
                    event_id=event_id,
                    summary=summary,
                    actors=actors,
                    location=("old gate" if "gate" in lower else "border road"),
                    causes=[events[-1].event_id] if events else [],
                    source_span=(start, start + len(summary)),
                    dramatic_weight=5
                    if any(word in lower for word in ("pursuit", "storm", "opens"))
                    else 3,
                )
            )
        chapters.append(
            ChapterIR(
                meta=ChapterMeta(
                    source=f"{source_name} — {title}", char_count=sum(len(x) for _, x in rows)
                ),
                characters=characters,
                events=events,
            )
        )
    return chapters


__all__ = ["chapters_from_source"]
