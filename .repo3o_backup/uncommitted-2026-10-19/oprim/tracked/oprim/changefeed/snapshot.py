"""Changefeed snapshot — serialize full stratum state to JSON for cold-start sync.

Canonical stratum tables are the plural contract (``substrates`` / ``concepts`` /
``notes``) used by oskill sync consumers. The legacy singular names from the
11a6f0b era (``substrate`` / ``concept`` / ``note``) are accepted on restore and
used on create only when the plural table is absent — no data is ever silently
dropped or double-counted.

Restored from Phase 2 Wave 2 (commit 11a6f0b) and adapted to the current
consumer schema (oskill.sync): plural tables ``substrates`` / ``concepts`` /
``notes`` with the consumer column set, plus lazy schema bootstrap.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import UTC, datetime

from oprim._logging import log
from oprim.changefeed._bootstrap import ensure_schema
from oprim.changefeed.reader import ChangefeedReader
from oprim.errors import MetaDBError
from oprim.meta_db.duckdb import MetaDB

_FORMAT = "stratum_snapshot_v1"

# (canonical plural table, legacy singular alias)
_TABLES: tuple[tuple[str, str], ...] = (
    ("substrates", "substrate"),
    ("concepts", "concept"),
    ("notes", "note"),
)


def _table_exists(db: MetaDB, table: str) -> bool:
    rows = db.fetchall(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
        [table],
    )
    return bool(rows and rows[0][0])


def _table_columns(db: MetaDB, table: str) -> list[str]:
    cur = db.execute(f"SELECT * FROM {table} LIMIT 0")
    return [d[0] for d in cur.description]


def _dump_table(db: MetaDB, table: str) -> list[dict]:
    """Dump all rows of *table* as column-name dicts; [] when the table is absent."""
    if not _table_exists(db, table):
        return []
    cur = db.execute(f"SELECT * FROM {table}")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


class ChangefeedSnapshot:
    """Creates and restores full-state snapshots for cross-device cold start."""

    def __init__(self, db: MetaDB) -> None:
        ensure_schema(db)
        self.db = db

    async def create_snapshot(
        self,
        user_id: str,
        device_id: str,
        storage_adapter,
    ) -> dict:
        """Serialize current stratum state, upload to storage, record in changefeed_snapshots."""
        ensure_schema(self.db)
        reader = ChangefeedReader(self.db, user_id)
        seq_at = reader.get_latest_seq()

        snapshot_id = uuid.uuid4().hex
        created_at = datetime.now(tz=UTC)

        dumped: dict[str, list[dict]] = {}
        for plural, singular in _TABLES:
            rows = _dump_table(self.db, plural)
            if not rows and not _table_exists(self.db, plural):
                rows = _dump_table(self.db, singular)
            dumped[plural] = rows

        data = {
            "format": _FORMAT,
            "snapshot_id": snapshot_id,
            "user_id": user_id,
            "device_id": device_id,
            "seq_at": seq_at,
            "created_at": created_at.isoformat(),
            "substrates": dumped["substrates"],
            "concepts": dumped["concepts"],
            "notes": dumped["notes"],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
            json.dump(data, tf, ensure_ascii=False, default=str)
            tmp_path = tf.name

        remote_path = f"snapshots/snapshot_{user_id}_{seq_at}.json"
        try:
            result = await storage_adapter.upload(
                tmp_path, remote_path, mime_type="application/json"
            )
            file_id = result.file_id
        finally:
            os.unlink(tmp_path)

        self.db.execute(
            "INSERT INTO changefeed_snapshots (id, user_id, device_id, seq_at, file_id)"
            " VALUES (?, ?, ?, ?, ?)",
            [snapshot_id, user_id, device_id, seq_at, file_id],
        )

        log.info(
            "snapshot_created",
            snapshot_id=snapshot_id,
            seq_at=seq_at,
            file_id=file_id,
            user_id=user_id,
        )
        return {
            "snapshot_id": snapshot_id,
            "seq_at": seq_at,
            "file_id": file_id,
            "substrate_count": len(dumped["substrates"]),
            "concept_count": len(dumped["concepts"]),
            "note_count": len(dumped["notes"]),
        }

    async def restore_from_snapshot(
        self,
        snapshot_file_id: str,
        storage_adapter,
    ) -> dict:
        """Download snapshot and repopulate local stratum tables.

        WARNING: This deletes existing substrates/concepts/notes rows before
        restoring. Should only be called on a fresh install or with explicit
        user consent.
        """
        ensure_schema(self.db)
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".json", delete=False) as tf:
            tmp_path = tf.name

        try:
            await storage_adapter.download(snapshot_file_id, tmp_path)
            with open(tmp_path, encoding="utf-8") as f:
                data = json.load(f)
        finally:
            os.unlink(tmp_path)

        if data.get("format") != _FORMAT:
            raise ValueError(f"Unknown snapshot format: {data.get('format')!r}")

        user_id = data.get("user_id", "")
        counts: dict[str, int] = {}
        for plural, singular in _TABLES:
            rows = data.get(plural) or data.get(singular) or []
            counts[plural] = self._restore_table(plural, singular, rows, user_id)

        seq_at = data.get("seq_at", 0)
        log.info(
            "snapshot_restored",
            snapshot_file_id=snapshot_file_id,
            seq_at=seq_at,
            substrate_count=counts["substrates"],
        )
        return {
            "seq_at": seq_at,
            "snapshot_id": data.get("snapshot_id"),
            "substrate_count": counts["substrates"],
            "concept_count": counts["concepts"],
            "note_count": counts["notes"],
        }

    def _restore_table(self, plural: str, singular: str, rows: list[dict], user_id: str) -> int:
        """Replace the stratum table contents with *rows*; return restored count."""
        if _table_exists(self.db, plural):
            target = plural
        elif _table_exists(self.db, singular):
            target = singular
        else:
            raise MetaDBError(f"Cannot restore snapshot: neither {plural} nor {singular} exists")
        actual = set(_table_columns(self.db, target))
        self.db.execute(f"DELETE FROM {target}")
        restored = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            record = {k: v for k, v in row.items() if k in actual}
            if "user_id" in actual and not record.get("user_id") and user_id:
                record["user_id"] = user_id
            if not record:
                continue
            cols = sorted(record.keys())
            placeholders = ", ".join("?" * len(cols))
            self.db.execute(
                f"INSERT INTO {target} ({', '.join(cols)}) VALUES ({placeholders})",
                [record[c] for c in cols],
            )
            restored += 1
        return restored

    def list_snapshots(self, user_id: str) -> list[dict]:
        """Return all snapshots for user, newest first."""
        ensure_schema(self.db)
        rows = self.db.fetchall(
            "SELECT id, user_id, device_id, seq_at, file_id, created_at "
            "FROM changefeed_snapshots WHERE user_id = ? ORDER BY seq_at DESC",
            [user_id],
        )
        return [
            {
                "snapshot_id": r[0],
                "user_id": r[1],
                "device_id": r[2],
                "seq_at": r[3],
                "file_id": r[4],
                "created_at": str(r[5]),
            }
            for r in rows
        ]
