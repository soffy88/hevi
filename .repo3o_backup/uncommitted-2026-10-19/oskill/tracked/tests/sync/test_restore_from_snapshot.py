"""Tests for restore_from_snapshot skill."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from oprim.storage.protocol import UploadResult

from oskill.sync.errors import SnapshotError
from oskill.sync.restore_from_snapshot import restore_from_snapshot
from oskill.sync.snapshot_backup import snapshot_backup

USER = "u1"
DEVICE = "device_A"

_SNAPSHOT_V1 = "stratum_snapshot_v1"


def _make_snapshot_content(
    snapshot_id: str = "snap1",
    seq_at: int = 5,
    substrates: list | None = None,
    concepts: list | None = None,
    notes: list | None = None,
) -> str:
    return json.dumps(
        {
            "format": _SNAPSHOT_V1,
            "snapshot_id": snapshot_id,
            "user_id": USER,
            "device_id": DEVICE,
            "seq_at": seq_at,
            "created_at": "2026-05-20T10:00:00",
            "substrate": substrates or [],
            "concept": concepts or [],
            "note": notes or [],
        },
        ensure_ascii=False,
    )


def _make_storage(snapshot_content: str) -> MagicMock:
    s = MagicMock()
    s.upload = AsyncMock(return_value=UploadResult(file_id="snap_f1", size=100, md5="x"))

    async def download(file_id, local_path, on_progress=None):
        Path(local_path).write_bytes(snapshot_content.encode())

    s.download = download
    return s


class TestRestoreFromSnapshot:
    async def test_returns_restore_result(self, db):
        content = _make_snapshot_content(snapshot_id="snap1", seq_at=3)
        storage = _make_storage(content)

        result = await restore_from_snapshot("snap_f1", db, storage)
        assert result["snapshot_id"] == "snap1"
        assert result["seq_at"] == 3

    async def test_restores_substrate_rows(self, db):
        sub_row = {
            "id": "sub_1",
            "ulid": "01HX",
            "title": "Doc A",
            "mime": "application/pdf",
            "source_path": None,
            "file_hash": None,
            "byte_size": 0,
            "page_count": 1,
            "parser": None,
            "language": "en",
            "has_cjk": False,
            "is_scanned": False,
            "created_at": "2026-05-01T00:00:00",
            "updated_at": "2026-05-01T00:00:00",
            "meta_json": "{}",
        }
        content = _make_snapshot_content(substrates=[sub_row])
        storage = _make_storage(content)

        await restore_from_snapshot("snap_f1", db, storage)
        rows = db.fetchall("SELECT id, title FROM substrates WHERE id = 'sub_1'")
        assert rows[0][1] == "Doc A"

    async def test_truncates_existing_data(self, db):
        from tests.sync.conftest import seed_substrate

        seed_substrate(db, "old_sub", "OLD_ULID")

        content = _make_snapshot_content()  # empty substrates
        storage = _make_storage(content)

        await restore_from_snapshot("snap_f1", db, storage)
        rows = db.fetchall("SELECT id FROM substrates WHERE id = 'old_sub'")
        assert rows == []

    async def test_restores_note_rows(self, db):
        note_row = {
            "id": "note_1",
            "title": "My Note",
            "content": "Hello",
            "wikilinks": "[]",
            "substrate_id": None,
            "meta_json": "{}",
            "created_at": "2026-05-01T00:00:00",
            "updated_at": "2026-05-01T00:00:00",
        }
        content = _make_snapshot_content(notes=[note_row])
        storage = _make_storage(content)

        await restore_from_snapshot("snap_f1", db, storage)
        rows = db.fetchall("SELECT title FROM notes WHERE id = 'note_1'")
        assert rows[0][0] == "My Note"

    async def test_restores_concept_rows(self, db):
        concept_row = {
            "id": "c_1",
            "name": "Alpha",
            "aliases": None,
            "description": None,
            "wikilink": "alpha",
            "source_ids": "[]",
            "meta_json": "{}",
            "created_at": "2026-05-01T00:00:00",
            "updated_at": "2026-05-01T00:00:00",
        }
        content = _make_snapshot_content(concepts=[concept_row])
        storage = _make_storage(content)

        await restore_from_snapshot("snap_f1", db, storage)
        rows = db.fetchall("SELECT name FROM concepts WHERE id = 'c_1'")
        assert rows[0][0] == "Alpha"

    async def test_raises_snapshot_error_on_bad_format(self, db):
        content = json.dumps({"format": "unknown_v99"})
        storage = _make_storage(content)

        with pytest.raises(SnapshotError, match="snapshot"):
            await restore_from_snapshot("snap_f1", db, storage)

    async def test_raises_snapshot_error_on_download_failure(self, db):
        storage = MagicMock()
        storage.download = AsyncMock(side_effect=RuntimeError("network error"))

        with pytest.raises(SnapshotError, match="network error"):
            await restore_from_snapshot("snap_f1", db, storage)

    async def test_round_trip_backup_restore(self, db):
        from tests.sync.conftest import seed_note, seed_substrate

        seed_substrate(db, "sub_1", "01HX")
        seed_note(db, "note_1")

        # Backup
        storage_upload = MagicMock()
        storage_upload.upload = AsyncMock(
            return_value=UploadResult(file_id="snap_f1", size=1000, md5="x")
        )
        await snapshot_backup(USER, DEVICE, db, storage_upload)

        # Capture what was uploaded
        call_args = storage_upload.upload.call_args
        call_args.args[0]

        # The file was deleted after upload, so we'll re-create it from what we know
        # Instead, test round-trip by doing backup then restore using the actual file

        # Use a persistent temp file to capture uploaded content

        content_holder: list[str] = []

        async def capture_upload(local_path, remote_path, mime_type=None):
            content_holder.append(Path(local_path).read_text())
            return UploadResult(file_id="snap_f2", size=100, md5="y")

        storage2 = MagicMock()
        storage2.upload = capture_upload
        await snapshot_backup(USER, DEVICE, db, storage2)

        # Restore onto a fresh db
        from oprim.meta_db.duckdb import open_meta_db

        with tempfile.TemporaryDirectory() as td:
            db2 = open_meta_db(Path(td) / "meta.duckdb")
            from tests.sync.conftest import _SCHEMA_DDL

            for stmt in _SCHEMA_DDL.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    db2.execute(stmt)

            storage3 = _make_storage(content_holder[0])
            await restore_from_snapshot("snap_f2", db2, storage3)

            rows = db2.fetchall("SELECT id FROM substrates WHERE id = 'sub_1'")
            assert len(rows) == 1
            db2.close()
