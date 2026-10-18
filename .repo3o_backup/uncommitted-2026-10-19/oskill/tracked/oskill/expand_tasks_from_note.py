from __future__ import annotations

import hashlib
import unicodedata
from datetime import date

from oprim.parse_obsidian_tasks import parse_obsidian_tasks
from pydantic import BaseModel, Field


class NormalizedTask(BaseModel):
    """标准化后的任务."""

    text: str
    completed: bool
    due_date: date | None = None
    scheduled_date: date | None = None
    tags: list[str] = Field(default_factory=list)
    source_line: int
    fingerprint: str


def expand_tasks_from_note(note_content: str) -> list[NormalizedTask]:
    """从笔记中提取任务并进行标准化、去重.

    Args:
        note_content: 笔记全文 (Markdown)

    Returns:
        归一化并去重后的任务列表.

    Example:
        ```python
        note = "- [ ]  Buy Milk 📅 2024-05-20\\n- [ ] Buy milk 📅 2024-05-20"
        tasks = expand_tasks_from_note(note)
        assert len(tasks) == 1
        assert tasks[0].fingerprint != ""
        ```
    """
    if not note_content or not note_content.strip():
        return []

    raw_tasks = parse_obsidian_tasks(content=note_content)

    normalized = []
    for t in raw_tasks:
        # Normalize text: NFKC + strip
        norm_text = unicodedata.normalize("NFKC", t.text).strip()

        # Canonical representation for fingerprint
        parts = [
            norm_text.lower(),
            str(t.completed),
            t.due_date.isoformat() if t.due_date else "",
            t.scheduled_date.isoformat() if t.scheduled_date else "",
            ",".join(sorted(t.tags)),
        ]
        canonical = "|".join(parts)

        fp = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

        normalized.append(
            NormalizedTask(
                text=norm_text,
                completed=t.completed,
                due_date=t.due_date,
                scheduled_date=t.scheduled_date,
                tags=t.tags,
                source_line=t.line_number,
                fingerprint=fp,
            )
        )

    # Deduplicate: keep the one with smallest source_line
    dedup_map: dict[str, NormalizedTask] = {}
    for nt in normalized:
        if nt.fingerprint not in dedup_map:
            dedup_map[nt.fingerprint] = nt
        else:
            if nt.source_line < dedup_map[nt.fingerprint].source_line:
                dedup_map[nt.fingerprint] = nt

    # Return sorted by source_line
    return sorted(list(dedup_map.values()), key=lambda x: x.source_line)
