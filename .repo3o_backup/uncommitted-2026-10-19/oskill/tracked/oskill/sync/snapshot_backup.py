"""oskill.sync.snapshot_backup — trigger a full-state snapshot and upload to storage."""

from __future__ import annotations

from oprim._logging import log
from oprim.changefeed.snapshot import ChangefeedSnapshot
from oprim.meta_db.duckdb import MetaDB

from oskill.sync.errors import SnapshotError


async def snapshot_backup(
    user_id: str,
    device_id: str,
    db: MetaDB,
    storage_adapter,
) -> dict:
    """Serialize the current DB state to a snapshot and upload to remote storage.

    Delegates to oprim.changefeed.ChangefeedSnapshot.create_snapshot.
    Returns a dict with keys: snapshot_id, seq_at, file_id, substrate_count,
    concept_count, note_count.

    Raises SnapshotError on failure.
    """
    try:
        cs = ChangefeedSnapshot(db)
        result = await cs.create_snapshot(user_id, device_id, storage_adapter)
    except Exception as exc:
        log.error("snapshot_backup_failed", user_id=user_id, device_id=device_id, error=str(exc))
        raise SnapshotError(f"Snapshot backup failed: {exc}") from exc

    log.info(
        "snapshot_backup_complete",
        snapshot_id=result.get("snapshot_id"),
        seq_at=result.get("seq_at"),
        user_id=user_id,
    )
    return result
