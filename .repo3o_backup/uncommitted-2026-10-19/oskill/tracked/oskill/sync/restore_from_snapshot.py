"""oskill.sync.restore_from_snapshot — download a snapshot and restore local DB."""

from __future__ import annotations

from oprim._logging import log
from oprim.changefeed.snapshot import ChangefeedSnapshot
from oprim.meta_db.duckdb import MetaDB

from oskill.sync.errors import SnapshotError


async def restore_from_snapshot(
    snapshot_file_id: str,
    db: MetaDB,
    storage_adapter,
) -> dict:
    """Download a snapshot from storage and restore the local DB.

    WARNING: This truncates the substrate, concept, and note tables before
    restoring. Use only on fresh installs or with explicit user confirmation.

    Delegates to oprim.changefeed.ChangefeedSnapshot.restore_from_snapshot.
    Returns a dict with keys: seq_at, snapshot_id, substrate_count,
    concept_count, note_count.

    Raises SnapshotError on failure.
    """
    try:
        cs = ChangefeedSnapshot(db)
        result = await cs.restore_from_snapshot(snapshot_file_id, storage_adapter)
    except Exception as exc:
        log.error(
            "restore_from_snapshot_failed",
            snapshot_file_id=snapshot_file_id,
            error=str(exc),
        )
        raise SnapshotError(f"Restore from snapshot failed: {exc}") from exc

    log.info(
        "restore_from_snapshot_complete",
        snapshot_id=result.get("snapshot_id"),
        seq_at=result.get("seq_at"),
    )
    return result
