"""Atomic JSON persistence for canonical narrative assets."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from hevi.narrative.bible import restore_bible, validate_bible
from hevi.narrative.models import RevisionReceipt, StoryBible, to_dict


def persist_bible(bible: StoryBible, path: Path, previous_revision: str | None = None) -> RevisionReceipt:
    validate_bible(bible)
    payload = json.dumps(to_dict(bible), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        restore_bible(json.loads(path.read_text(encoding="utf-8")))
    finally:
        temp.unlink(missing_ok=True)
    return RevisionReceipt(str(path), previous_revision, bible.revision, True, "PASS")


def revision_hash(bible: StoryBible) -> str:
    return hashlib.sha256(json.dumps(to_dict(bible), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
