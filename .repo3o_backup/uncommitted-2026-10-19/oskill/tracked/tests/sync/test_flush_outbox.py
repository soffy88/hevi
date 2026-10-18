"""Tests for flush_outbox skill."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from oprim.changefeed.schema import EventType
from oprim.changefeed.writer import ChangefeedWriter
from oprim.storage.protocol import UploadResult

from oskill.sync.errors import FlushError
from oskill.sync.flush_outbox import _load_state, _state_path, flush_outbox

USER = "u1"
DEVICE = "device_A"


async def _write_event(db, device_id=DEVICE, user_id=USER):
    writer = ChangefeedWriter(db, user_id, device_id)
    return await writer.append(EventType.SUBSTRATE_CREATED, "sub_1", {"title": "doc"})


class TestFlushOutboxNothingToFlush:
    async def test_empty_db_returns_zero(self, db, storage, tmp_path):
        result = await flush_outbox(USER, DEVICE, db, storage, state_dir=tmp_path)
        assert result.flushed_count == 0
        assert result.failed_count == 0
        assert result.last_flushed_seq == 0
        assert result.uploaded_files == []
        storage.upload.assert_not_called()

    async def test_only_remote_events_not_uploaded(self, db, storage, tmp_path):
        # Write event from a different device
        writer = ChangefeedWriter(db, USER, "device_B")
        await writer.append(EventType.SUBSTRATE_CREATED, "sub_1", {"title": "doc"})

        result = await flush_outbox(USER, DEVICE, db, storage, state_dir=tmp_path)
        assert result.flushed_count == 0
        storage.upload.assert_not_called()


class TestFlushOutboxUploads:
    async def test_flushes_own_events(self, db, storage, tmp_path):
        await _write_event(db)
        result = await flush_outbox(USER, DEVICE, db, storage, state_dir=tmp_path)
        assert result.flushed_count == 1
        assert result.failed_count == 0
        assert result.last_flushed_seq == 1
        assert len(result.uploaded_files) == 1
        assert DEVICE in result.uploaded_files[0]
        storage.upload.assert_called_once()

    async def test_uploaded_file_is_valid_jsonl(self, db, storage, tmp_path):
        await _write_event(db)
        captured_path: list[str] = []

        async def capture_upload(local_path, remote_path, mime_type=None):
            captured_path.append(local_path)
            return UploadResult(file_id="f1", size=10, md5="x")

        storage.upload = capture_upload
        await flush_outbox(USER, DEVICE, db, storage, state_dir=tmp_path)

        # The tmp file is deleted after upload, but we captured before deletion
        # Instead, verify the remote_path format
        # Re-run and intercept before deletion
        await _write_event(db)
        content_holder: list[str] = []

        async def capture_content(local_path, remote_path, mime_type=None):
            content_holder.append(Path(local_path).read_text())
            return UploadResult(file_id="f2", size=20, md5="y")

        storage.upload = capture_content
        await flush_outbox(USER, DEVICE, db, storage, state_dir=tmp_path)
        assert len(content_holder) == 1
        line = json.loads(content_holder[0].splitlines()[0])
        assert line["event_type"] == "substrate.created"

    async def test_state_saved_after_flush(self, db, storage, tmp_path):
        await _write_event(db)
        await flush_outbox(USER, DEVICE, db, storage, state_dir=tmp_path)

        state = _load_state(_state_path(USER, DEVICE, tmp_path))
        assert state["last_flushed_seq"] == 1

    async def test_second_flush_only_new_events(self, db, storage, tmp_path):
        await _write_event(db)
        await flush_outbox(USER, DEVICE, db, storage, state_dir=tmp_path)
        call_count_after_first = storage.upload.call_count

        # No new events — second flush should not upload
        result = await flush_outbox(USER, DEVICE, db, storage, state_dir=tmp_path)
        assert result.flushed_count == 0
        assert storage.upload.call_count == call_count_after_first

    async def test_multiple_events_in_one_flush(self, db, storage, tmp_path):
        writer = ChangefeedWriter(db, USER, DEVICE)
        await writer.append(EventType.SUBSTRATE_CREATED, "sub_1", {"title": "A"})
        await writer.append(EventType.SUBSTRATE_UPDATED, "sub_1", {"title": "A2"})
        await writer.append(EventType.NOTE_CREATED, "note_1", {"title": "N"})

        result = await flush_outbox(USER, DEVICE, db, storage, state_dir=tmp_path)
        assert result.flushed_count == 3
        assert result.last_flushed_seq == 3

    async def test_remote_path_contains_seq_range(self, db, storage, tmp_path):
        writer = ChangefeedWriter(db, USER, DEVICE)
        await writer.append(EventType.SUBSTRATE_CREATED, "sub_1", {"title": "A"})
        await writer.append(EventType.SUBSTRATE_UPDATED, "sub_1", {"title": "B"})

        result = await flush_outbox(USER, DEVICE, db, storage, state_dir=tmp_path)
        assert len(result.uploaded_files) == 1
        # path format: Stratum/changefeed/events_{device_id}_{start}_{end}.jsonl
        path = result.uploaded_files[0]
        assert f"events_{DEVICE}_1_2.jsonl" in path


class TestFlushOutboxErrors:
    async def test_upload_failure_raises_flush_error(self, db, storage, tmp_path):
        await _write_event(db)
        storage.upload = AsyncMock(side_effect=RuntimeError("network timeout"))

        with pytest.raises(FlushError, match="network timeout"):
            await flush_outbox(USER, DEVICE, db, storage, state_dir=tmp_path)

    async def test_state_not_updated_on_failure(self, db, storage, tmp_path):
        await _write_event(db)
        storage.upload = AsyncMock(side_effect=RuntimeError("gone"))

        with pytest.raises(FlushError):
            await flush_outbox(USER, DEVICE, db, storage, state_dir=tmp_path)

        state = _load_state(_state_path(USER, DEVICE, tmp_path))
        assert state.get("last_flushed_seq", 0) == 0
