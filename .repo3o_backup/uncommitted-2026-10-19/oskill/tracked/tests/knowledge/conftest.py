"""Fixtures for knowledge skill tests."""

from __future__ import annotations

import fitz
import pytest
from PIL import Image

# ---------------------------------------------------------------------------
# Stratum v1.1 schema (SPEC v1.1 §M2: substrate→substrates, note→notes,
# concept→concepts). Used instead of oprim migrations because 001_initial.sql
# still uses the old singular names.
# ---------------------------------------------------------------------------
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
CREATE TABLE IF NOT EXISTS derivative (
    id            TEXT PRIMARY KEY,
    substrate_id  TEXT,
    kind          TEXT,
    content       TEXT,
    embedding_id  TEXT,
    embedding_dim INTEGER,
    meta_json     TEXT DEFAULT '{}',
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
CREATE TABLE IF NOT EXISTS notes (
    id           TEXT PRIMARY KEY,
    title        TEXT,
    content      TEXT,
    wikilinks    TEXT DEFAULT '[]',
    substrate_id TEXT,
    meta_json    TEXT DEFAULT '{}',
    created_at   TEXT,
    updated_at   TEXT
);
CREATE SEQUENCE IF NOT EXISTS changefeed_seq;
CREATE TABLE IF NOT EXISTS changefeed_local (
    seq        BIGINT,
    table_name TEXT,
    row_id     TEXT,
    op         TEXT,
    payload    TEXT
);
CREATE TABLE IF NOT EXISTS views (
    id                    TEXT PRIMARY KEY,
    user_id               TEXT NOT NULL,
    name                  TEXT NOT NULL,
    description           TEXT,
    default_filter        TEXT,
    default_llm           TEXT,
    default_system_prompt TEXT,
    icon                  TEXT,
    is_default            BOOLEAN DEFAULT FALSE,
    is_builtin            BOOLEAN DEFAULT FALSE,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);
"""


@pytest.fixture()
def stratum_home(tmp_path, monkeypatch):
    """Monkeypatch STRATUM_HOME to a temp directory."""
    home = tmp_path / "stratum"
    home.mkdir()
    # Patch env and the cfg store
    monkeypatch.setenv("STRATUM_HOME", str(home))
    import oprim._config as _cfg_mod

    _cfg_mod._store["STRATUM_HOME"] = str(home)
    yield home
    # Cleanup
    _cfg_mod._store.pop("STRATUM_HOME", None)


@pytest.fixture()
def stratum_schema(stratum_home):
    """Pre-create Stratum v1.1 schema (plural names) in the test DuckDB.

    Bypasses oprim migrations (001_initial.sql still uses singular names).
    Returns the stratum_home path so it can serve as a drop-in replacement.
    """
    from oprim.meta_db import open_meta_db

    from oskill.knowledge._context import meta_db_path

    db_p = meta_db_path()
    db = open_meta_db(db_p)
    for stmt in _SCHEMA_DDL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            db.execute(stmt)
    db.close()
    yield stratum_home


@pytest.fixture()
def simple_pdf(tmp_path):
    path = tmp_path / "test.pdf"
    doc = fitz.open()
    page = doc.new_page()
    for i, line in enumerate(
        [
            "Hello World test PDF content for testing purposes.",
            "Second line: more content here.",
            "Third line: plenty of extractable text.",
            "Fourth line: more text to exceed scanned threshold.",
        ]
    ):
        page.insert_text((50, 50 + i * 20), line)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture()
def simple_txt(tmp_path):
    path = tmp_path / "test.txt"
    path.write_text("Hello world! This is a plain text file.\n" * 10)
    return path


@pytest.fixture()
def simple_md(tmp_path):
    path = tmp_path / "note.md"
    path.write_text(
        "# Test Note\n\nThis is a markdown note with some content.\n\nSecond paragraph here.\n"
    )
    return path


@pytest.fixture()
def simple_html(tmp_path):
    path = tmp_path / "page.html"
    path.write_text(
        "<html><head><title>Test</title></head><body>"
        "<h1>Test Article</h1>"
        "<p>This is a test HTML document with enough content to extract.</p>"
        "<p>Second paragraph for good measure.</p>"
        "</body></html>"
    )
    return path


@pytest.fixture()
def simple_png(tmp_path):
    path = tmp_path / "test.png"
    img = Image.new("RGB", (100, 100), color=(255, 0, 0))
    img.save(str(path))
    return path


@pytest.fixture()
def screen_png(tmp_path):
    path = tmp_path / "screenshot.png"
    img = Image.new("RGB", (1920, 1080), color=(0, 128, 255))
    img.save(str(path))
    return path
