"""SHA-256 exact-match duplicate detection. Phase 1: hash-only, no embedding similarity."""

from __future__ import annotations

from oprim._logging import log
from oprim.meta_db import open_meta_db

from oskill.knowledge._context import meta_db_path


async def detect_duplicate_substrate(
    file_hash: str,
    embedding: list[float] | None = None,
    similarity_threshold: float = 0.95,
) -> str | None:
    """Return existing substrate_id if duplicate, else None.

    Phase 1: SHA-256 exact match only. Embedding similarity lookup deferred to Phase 10.
    """
    db_path = meta_db_path()
    if not db_path.exists():
        return None

    try:
        db = open_meta_db(db_path)
        rows = db.fetchall("SELECT id FROM substrates WHERE file_hash = ?", [file_hash])
        db.close()
    except Exception as e:
        log.warning("oskill.detect_duplicate.db_error", error=str(e))
        return None

    if rows:
        existing_id = rows[0][0]
        log.info("oskill.detect_duplicate.found", file_hash=file_hash, existing_id=existing_id)
        return existing_id

    return None
