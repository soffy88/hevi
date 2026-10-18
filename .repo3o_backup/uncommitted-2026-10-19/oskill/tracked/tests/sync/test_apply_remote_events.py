"""Tests for apply_remote_events skill."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from oprim.storage.protocol import StorageFile

from oskill.sync.apply_remote_events import _parse_jsonl, apply_remote_events
from oskill.sync.errors import ApplyError
from tests.sync.conftest import (
    jsonl_content,
    make_event_dict,
    seed_concept,
    seed_note,
    seed_substrate,
)

USER = "u1"
DEVICE_A = "device_A"
DEVICE_B = "device_B"


def _make_storage_with_files(files: dict[str, str]) -> MagicMock:
    """files: {filename (name): jsonl_content_string}

    filename convention: events_{device_id}_{seq_start}_{seq_end}.jsonl
    Both file_id and name are set to filename for easy test setup.
    """
    storage = MagicMock()

    async def list_files(folder=None, recursive=False):
        for name in files:
            yield StorageFile(
                file_id=name,  # used as download handle in tests
                name=name,  # just the filename
                size=len(files[name]),
                mime_type="application/x-ndjson",
                created_at=None,  # type: ignore[arg-type]
                modified_at=None,  # type: ignore[arg-type]
                md5=None,
            )

    storage.list_files = list_files

    async def download(file_id, local_path, on_progress=None):
        content = files.get(file_id, "")
        Path(local_path).write_bytes(content.encode())

    storage.download = download
    return storage


class TestApplyRemoteNoFiles:
    async def test_no_remote_files_returns_zero(self, db, storage, tmp_path):
        result = await apply_remote_events(USER, DEVICE_A, db, storage, state_dir=tmp_path)
        assert result.applied_count == 0
        assert result.skipped_count == 0

    async def test_own_device_files_skipped(self, db, tmp_path):
        storage = _make_storage_with_files({f"events_{DEVICE_A}_1_1.jsonl": ""})
        result = await apply_remote_events(USER, DEVICE_A, db, storage, state_dir=tmp_path)
        assert result.applied_count == 0


class TestApplySubstrate:
    async def test_substrate_created_inserted(self, db, tmp_path):
        ev = make_event_dict(
            "substrate.created",
            "sub_1",
            {
                "id": "sub_1",
                "ulid": "01HX",
                "title": "Remote Doc",
                "mime": "application/pdf",
                "meta_json": "{}",
            },
            device_id=DEVICE_B,
        )
        storage = _make_storage_with_files({f"events_{DEVICE_B}_1_1.jsonl": jsonl_content(ev)})
        result = await apply_remote_events(USER, DEVICE_A, db, storage, state_dir=tmp_path)
        assert result.applied_count == 1

        rows = db.fetchall("SELECT id, title FROM substrates WHERE id = 'sub_1'")
        assert len(rows) == 1
        assert rows[0][1] == "Remote Doc"

    async def test_substrate_updated_overwrites(self, db, tmp_path):
        seed_substrate(db, "sub_1", "01HX")

        ev = make_event_dict(
            "substrate.updated",
            "sub_1",
            {"id": "sub_1", "ulid": "01HX", "title": "Updated Title", "meta_json": "{}"},
            device_id=DEVICE_B,
        )
        storage = _make_storage_with_files({f"events_{DEVICE_B}_1_1.jsonl": jsonl_content(ev)})
        await apply_remote_events(USER, DEVICE_A, db, storage, state_dir=tmp_path)

        rows = db.fetchall("SELECT title FROM substrates WHERE id = 'sub_1'")
        assert rows[0][0] == "Updated Title"

    async def test_substrate_deleted_removes_row(self, db, tmp_path):
        seed_substrate(db, "sub_1", "01HX")

        ev = make_event_dict(
            "substrate.deleted",
            "sub_1",
            {"id": "sub_1"},
            device_id=DEVICE_B,
        )
        storage = _make_storage_with_files({f"events_{DEVICE_B}_1_1.jsonl": jsonl_content(ev)})
        await apply_remote_events(USER, DEVICE_A, db, storage, state_dir=tmp_path)

        rows = db.fetchall("SELECT id FROM substrates WHERE id = 'sub_1'")
        assert rows == []

    async def test_substrate_pin_updates_meta_json(self, db, tmp_path):
        seed_substrate(db, "sub_1", "01HX")

        ev = make_event_dict(
            "substrate.pinned",
            "sub_1",
            {"meta_json": '{"pinned": true}'},
            device_id=DEVICE_B,
        )
        storage = _make_storage_with_files({f"events_{DEVICE_B}_1_1.jsonl": jsonl_content(ev)})
        await apply_remote_events(USER, DEVICE_A, db, storage, state_dir=tmp_path)

        rows = db.fetchall("SELECT meta_json FROM substrates WHERE id = 'sub_1'")
        assert '"pinned"' in rows[0][0] or "pinned" in rows[0][0]

    async def test_substrate_unpin_updates_meta_json(self, db, tmp_path):
        seed_substrate(db, "sub_1", "01HX")

        ev = make_event_dict(
            "substrate.unpinned",
            "sub_1",
            {"meta_json": "{}"},
            device_id=DEVICE_B,
        )
        storage = _make_storage_with_files({f"events_{DEVICE_B}_1_1.jsonl": jsonl_content(ev)})
        await apply_remote_events(USER, DEVICE_A, db, storage, state_dir=tmp_path)


class TestApplyNote:
    async def test_note_created(self, db, tmp_path):
        ev = make_event_dict(
            "note.created",
            "note_1",
            {
                "id": "note_1",
                "title": "Note A",
                "content": "Hello",
                "wikilinks": "[]",
                "meta_json": "{}",
            },
            device_id=DEVICE_B,
        )
        storage = _make_storage_with_files({f"events_{DEVICE_B}_1_1.jsonl": jsonl_content(ev)})
        result = await apply_remote_events(USER, DEVICE_A, db, storage, state_dir=tmp_path)
        assert result.applied_count == 1
        rows = db.fetchall("SELECT title FROM notes WHERE id = 'note_1'")
        assert rows[0][0] == "Note A"

    async def test_note_updated(self, db, tmp_path):
        seed_note(db, "note_1", "Old Title")
        ev = make_event_dict(
            "note.updated",
            "note_1",
            {
                "id": "note_1",
                "title": "New Title",
                "content": "x",
                "wikilinks": "[]",
                "meta_json": "{}",
            },
            device_id=DEVICE_B,
        )
        storage = _make_storage_with_files({f"events_{DEVICE_B}_1_1.jsonl": jsonl_content(ev)})
        await apply_remote_events(USER, DEVICE_A, db, storage, state_dir=tmp_path)
        rows = db.fetchall("SELECT title FROM notes WHERE id = 'note_1'")
        assert rows[0][0] == "New Title"

    async def test_note_deleted(self, db, tmp_path):
        seed_note(db, "note_1")
        ev = make_event_dict("note.deleted", "note_1", {"id": "note_1"}, device_id=DEVICE_B)
        storage = _make_storage_with_files({f"events_{DEVICE_B}_1_1.jsonl": jsonl_content(ev)})
        await apply_remote_events(USER, DEVICE_A, db, storage, state_dir=tmp_path)
        rows = db.fetchall("SELECT id FROM notes WHERE id = 'note_1'")
        assert rows == []


class TestApplyConcept:
    async def test_concept_created(self, db, tmp_path):
        ev = make_event_dict(
            "concept.created",
            "c_1",
            {
                "id": "c_1",
                "name": "Alpha",
                "wikilink": "alpha",
                "source_ids": "[]",
                "meta_json": "{}",
            },
            device_id=DEVICE_B,
        )
        storage = _make_storage_with_files({f"events_{DEVICE_B}_1_1.jsonl": jsonl_content(ev)})
        result = await apply_remote_events(USER, DEVICE_A, db, storage, state_dir=tmp_path)
        assert result.applied_count == 1
        rows = db.fetchall("SELECT name FROM concepts WHERE id = 'c_1'")
        assert rows[0][0] == "Alpha"

    async def test_concept_deleted(self, db, tmp_path):
        seed_concept(db, "c_1", "Alpha")
        ev = make_event_dict("derivative.deleted", "c_1", {"id": "c_1"}, device_id=DEVICE_B)
        storage = _make_storage_with_files({f"events_{DEVICE_B}_1_1.jsonl": jsonl_content(ev)})
        await apply_remote_events(USER, DEVICE_A, db, storage, state_dir=tmp_path)
        rows = db.fetchall("SELECT id FROM concepts WHERE id = 'c_1'")
        assert rows == []

    async def test_concept_linked(self, db, tmp_path):
        seed_concept(db, "c_1", "Alpha")
        ev = make_event_dict(
            "concept.linked",
            "c_1",
            {"source_ids": '["sub_1"]'},
            device_id=DEVICE_B,
        )
        storage = _make_storage_with_files({f"events_{DEVICE_B}_1_1.jsonl": jsonl_content(ev)})
        await apply_remote_events(USER, DEVICE_A, db, storage, state_dir=tmp_path)
        rows = db.fetchall("SELECT source_ids FROM concepts WHERE id = 'c_1'")
        assert "sub_1" in rows[0][0]

    async def test_concept_unlinked(self, db, tmp_path):
        seed_concept(db, "c_1", "Alpha")
        ev = make_event_dict(
            "concept.unlinked",
            "c_1",
            {"source_ids": "[]"},
            device_id=DEVICE_B,
        )
        storage = _make_storage_with_files({f"events_{DEVICE_B}_1_1.jsonl": jsonl_content(ev)})
        await apply_remote_events(USER, DEVICE_A, db, storage, state_dir=tmp_path)


class TestApplyEdgeCases:
    async def test_unknown_event_type_skipped(self, db, tmp_path):
        ev = make_event_dict("unknown.type", None, {}, device_id=DEVICE_B)
        storage = _make_storage_with_files({f"events_{DEVICE_B}_1_1.jsonl": jsonl_content(ev)})
        result = await apply_remote_events(USER, DEVICE_A, db, storage, state_dir=tmp_path)
        assert result.skipped_count >= 1

    async def test_malformed_jsonl_line_skipped(self, db, tmp_path):
        storage = _make_storage_with_files({f"events_{DEVICE_B}_1_1.jsonl": "not json\n{broken"})
        result = await apply_remote_events(USER, DEVICE_A, db, storage, state_dir=tmp_path)
        assert result.applied_count == 0

    async def test_empty_jsonl_file_handled(self, db, tmp_path):
        storage = _make_storage_with_files({f"events_{DEVICE_B}_1_1.jsonl": ""})
        result = await apply_remote_events(USER, DEVICE_A, db, storage, state_dir=tmp_path)
        assert result.applied_count == 0

    async def test_already_processed_file_not_reapplied(self, db, tmp_path):
        ev = make_event_dict(
            "substrate.created",
            "sub_1",
            {"id": "sub_1", "ulid": "01HX", "title": "Doc", "meta_json": "{}"},
            device_id=DEVICE_B,
        )
        fname = f"events_{DEVICE_B}_1_1.jsonl"
        storage = _make_storage_with_files({fname: jsonl_content(ev)})

        # First apply
        await apply_remote_events(USER, DEVICE_A, db, storage, state_dir=tmp_path)
        # Second apply — same file should not be reprocessed
        result = await apply_remote_events(USER, DEVICE_A, db, storage, state_dir=tmp_path)
        assert result.applied_count == 0

    async def test_list_files_error_raises_apply_error(self, db, tmp_path):
        storage = MagicMock()

        async def failing_list(*args, **kwargs):
            raise RuntimeError("storage offline")
            yield  # make it a generator

        storage.list_files = failing_list

        with pytest.raises(ApplyError, match="storage offline"):
            await apply_remote_events(USER, DEVICE_A, db, storage, state_dir=tmp_path)

    async def test_download_failure_logged_continues(self, db, tmp_path):
        storage = MagicMock()

        async def list_files(*args, **kwargs):
            yield StorageFile(
                file_id="f1",
                name=f"events_{DEVICE_B}_1_1.jsonl",
                size=10,
                mime_type="text/plain",
                created_at=None,  # type: ignore[arg-type]
                modified_at=None,  # type: ignore[arg-type]
                md5=None,
            )

        storage.list_files = list_files
        storage.download = AsyncMock(side_effect=RuntimeError("download gone"))

        result = await apply_remote_events(USER, DEVICE_A, db, storage, state_dir=tmp_path)
        assert "download" in result.errors[0]

    async def test_derivative_created_handled(self, db, tmp_path):
        ev = make_event_dict(
            "derivative.created",
            "c_1",
            {
                "id": "c_1",
                "name": "Beta",
                "wikilink": "beta",
                "source_ids": "[]",
                "meta_json": "{}",
            },
            device_id=DEVICE_B,
        )
        storage = _make_storage_with_files({f"events_{DEVICE_B}_1_1.jsonl": jsonl_content(ev)})
        result = await apply_remote_events(USER, DEVICE_A, db, storage, state_dir=tmp_path)
        assert result.applied_count == 1


class TestParseJsonl:
    def test_parses_valid_lines(self):
        content = '{"a": 1}\n{"b": 2}'
        result = _parse_jsonl(content)
        assert result == [{"a": 1}, {"b": 2}]

    def test_skips_blank_lines(self):
        content = '{"a": 1}\n\n{"b": 2}'
        result = _parse_jsonl(content)
        assert len(result) == 2

    def test_skips_malformed_lines(self):
        content = '{"a": 1}\nnot-json\n{"c": 3}'
        result = _parse_jsonl(content)
        assert len(result) == 2

    def test_empty_string(self):
        assert _parse_jsonl("") == []
