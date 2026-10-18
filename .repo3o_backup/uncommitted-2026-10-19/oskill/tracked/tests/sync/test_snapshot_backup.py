"""Tests for snapshot_backup skill."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from oprim.storage.protocol import UploadResult

from oskill.sync.errors import SnapshotError
from oskill.sync.snapshot_backup import snapshot_backup

USER = "u1"
DEVICE = "device_A"


def _make_storage(file_id: str = "snap_file_1") -> MagicMock:
    s = MagicMock()
    s.upload = AsyncMock(return_value=UploadResult(file_id=file_id, size=200, md5="ab"))
    return s


class TestSnapshotBackup:
    async def test_returns_snapshot_result(self, db):
        storage = _make_storage()
        result = await snapshot_backup(USER, DEVICE, db, storage)

        assert "snapshot_id" in result
        assert "seq_at" in result
        assert "file_id" in result
        assert result["file_id"] == "snap_file_1"

    async def test_records_in_db(self, db):
        storage = _make_storage()
        result = await snapshot_backup(USER, DEVICE, db, storage)

        rows = db.fetchall("SELECT id FROM changefeed_snapshots WHERE user_id = ?", [USER])
        assert len(rows) == 1
        assert rows[0][0] == result["snapshot_id"]

    async def test_upload_called_with_json_mime(self, db):
        storage = _make_storage()
        await snapshot_backup(USER, DEVICE, db, storage)

        call_args = storage.upload.call_args
        assert call_args.kwargs.get("mime_type") == "application/json"

    async def test_raises_snapshot_error_on_failure(self, db):
        storage = _make_storage()
        storage.upload = AsyncMock(side_effect=RuntimeError("storage full"))

        with pytest.raises(SnapshotError, match="storage full"):
            await snapshot_backup(USER, DEVICE, db, storage)

    async def test_empty_db_snapshot_has_zero_counts(self, db):
        storage = _make_storage()
        result = await snapshot_backup(USER, DEVICE, db, storage)

        assert result["substrate_count"] == 0
        assert result["concept_count"] == 0
        assert result["note_count"] == 0

    async def test_snapshot_counts_reflect_data(self, db):
        from tests.sync.conftest import seed_note, seed_substrate

        seed_substrate(db, "sub_1", "01HX")
        seed_note(db, "note_1")

        storage = _make_storage()
        result = await snapshot_backup(USER, DEVICE, db, storage)
        assert result["substrate_count"] == 1
        assert result["note_count"] == 1
