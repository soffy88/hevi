"""Shared fixtures for oskill.sync tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from oprim.meta_db.duckdb import open_meta_db
from oprim.storage.protocol import UploadResult

_MIGRATIONS_DIR = (
    Path(__file__).parent.parent.parent.parent / "oprim" / "oprim" / "meta_db" / "migrations"
)

_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS substrates (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    title        TEXT,
    mime         TEXT,
    source_path  TEXT,
    file_hash    TEXT,
    byte_size    BIGINT,
    page_count   INTEGER,
    parser       TEXT,
    language     TEXT,
    has_cjk      BOOLEAN DEFAULT FALSE,
    is_scanned   BOOLEAN DEFAULT FALSE,
    is_pinned    BOOLEAN DEFAULT FALSE,
    pinned_at    TEXT,
    pin_priority INTEGER DEFAULT 0,
    created_at   TEXT,
    updated_at   TEXT,
    meta_json    TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY, title TEXT, content TEXT,
    wikilinks TEXT DEFAULT '[]', substrate_id TEXT,
    meta_json TEXT DEFAULT '{}', created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS concepts (
    id                  TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL,
    name                TEXT NOT NULL,
    type                TEXT NOT NULL DEFAULT 'concept_idea',
    aliases             TEXT[],
    wikilink            TEXT,
    substrate_refs      TEXT[],
    related_concept_ids TEXT[],
    created_at          TEXT,
    deleted_at          TEXT
);
CREATE TABLE IF NOT EXISTS derivative (
    id TEXT PRIMARY KEY, substrate_id TEXT, kind TEXT,
    content TEXT, embedding_id TEXT, embedding_dim INTEGER,
    meta_json TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE SEQUENCE IF NOT EXISTS changefeed_seq;
CREATE TABLE IF NOT EXISTS changefeed_local (
    seq BIGINT, table_name TEXT, row_id TEXT, op TEXT, payload TEXT
);
"""


@pytest.fixture()
def db(tmp_path: Path):
    m = open_meta_db(tmp_path / "meta.duckdb")
    for stmt in _SCHEMA_DDL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            m.execute(stmt)
    yield m
    m.close()


def _make_storage_mock() -> MagicMock:
    """Return a mock StorageAdapter with sensible async defaults."""
    storage = MagicMock()
    storage.upload = AsyncMock(
        return_value=UploadResult(file_id="remote_id_1", size=100, md5="abc")
    )
    storage.download = AsyncMock()

    async def _empty_list(*args, **kwargs):
        return
        yield  # make it an async generator

    storage.list_files = _empty_list
    return storage


@pytest.fixture()
def storage():
    return _make_storage_mock()


def seed_substrate(db, sub_id: str = "sub_1", user_id: str = "test_user") -> None:
    db.execute(
        "INSERT INTO substrates (id, user_id, title, mime, meta_json) VALUES (?, ?, ?, ?, ?)",
        [sub_id, user_id, "Test Doc", "application/pdf", "{}"],
    )


def seed_note(db, note_id: str = "note_1", title: str = "My Note") -> None:
    db.execute(
        "INSERT INTO notes (id, title, content, wikilinks, meta_json) VALUES (?, ?, ?, ?, ?)",
        [note_id, title, "content", "[]", "{}"],
    )


def seed_concept(db, concept_id: str = "c_1", name: str = "Alpha") -> None:
    db.execute(
        "INSERT INTO concepts (id, user_id, name, type, wikilink) VALUES (?, ?, ?, ?, ?)",
        [concept_id, "test_user", name, "concept_idea", name.lower()],
    )


def make_event_dict(
    event_type: str,
    aggregate_id: str | None,
    payload: dict,
    device_id: str = "device_B",
    user_id: str = "u1",
    seq: int = 1,
) -> dict:
    return {
        "id": seq,
        "device_id": device_id,
        "user_id": user_id,
        "event_type": event_type,
        "aggregate_id": aggregate_id,
        "payload": payload,
        "created_at": "2026-05-20T10:00:00",
        "seq": seq,
    }


def jsonl_content(*event_dicts: dict) -> str:
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in event_dicts)
