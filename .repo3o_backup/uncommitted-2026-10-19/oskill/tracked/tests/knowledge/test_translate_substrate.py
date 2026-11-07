"""Tests for translate_substrate skill (async + embed_translation, ADR-020)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from oprim.meta_db import open_meta_db
from oprim.translate.protocol import TranslationResult

from oskill.translate_substrate import TranslateResult, translate_substrate


def _make_translate_result(text: str = "译文") -> TranslationResult:
    return TranslationResult(
        text=text,
        provider="mock",
        model="mock",
        input_tokens=10,
        output_tokens=10,
        cost_usd=0.001,
        source_lang="en",
        target_lang="zh",
    )


def _seed_substrate(db_path: Path, substrate_id: str, markdown_text: str) -> None:
    db = open_meta_db(db_path)
    db.execute(
        "CREATE TABLE IF NOT EXISTS substrates ("
        "id TEXT PRIMARY KEY, user_id TEXT, title TEXT, mime TEXT, source_path TEXT,"
        "file_hash TEXT, byte_size INTEGER, page_count INTEGER, parser TEXT,"
        "language TEXT, has_cjk BOOLEAN DEFAULT FALSE, is_scanned BOOLEAN DEFAULT FALSE,"
        "is_pinned BOOLEAN DEFAULT FALSE, meta_json TEXT DEFAULT '{}',"
        "created_at TEXT, updated_at TEXT)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS derivative ("
        "id TEXT PRIMARY KEY, substrate_id TEXT, kind TEXT, content TEXT,"
        "embedding_id TEXT, embedding_dim INTEGER, meta_json TEXT DEFAULT '{}',"
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    db.execute(
        """INSERT INTO substrates (id, title, meta_json, created_at, updated_at)
           VALUES (?, ?, '{}', current_timestamp, current_timestamp)""",
        [substrate_id, "Test"],
    )
    from ulid import ULID

    deriv_id = str(ULID())
    db.execute(
        "INSERT INTO derivative (id, substrate_id, kind, content) VALUES (?,?,?,?)",
        [deriv_id, substrate_id, "markdown", markdown_text],
    )
    db.close()


@pytest.mark.asyncio
async def test_translate_substrate_basic(stratum_home):
    db_path = stratum_home / "meta.duckdb"
    substrate_id = "01SUBSTRATE_TEST001"
    _seed_substrate(db_path, substrate_id, "Hello world. This is a test.")

    with (
        patch(
            "oskill.translate_substrate.translate_document_async",
            new_callable=AsyncMock,
        ) as mock_td,
        patch("oskill.translate_substrate._embed_translation", return_value=["v#0"]),
    ):
        mock_td.return_value = (
            "你好世界。这是一个测试。",
            [_make_translate_result()],
        )
        result = await translate_substrate(substrate_id, "zh", provider="deepseek")

    assert isinstance(result, TranslateResult)
    assert result.substrate_id == substrate_id
    assert result.target_lang == "zh"
    assert result.chunks_translated == 1
    assert result.derivative_id != ""
    assert result.embedding_ids == ["v#0"]

    db = open_meta_db(db_path)
    rows = db.execute(
        "SELECT kind, content FROM derivative WHERE id = ?",
        [result.derivative_id],
    ).fetchall()
    db.close()
    assert len(rows) == 1
    assert rows[0][0] == "translation_zh"
    assert "你好世界" in rows[0][1]


@pytest.mark.asyncio
async def test_translate_substrate_embed_false(stratum_home):
    db_path = stratum_home / "meta.duckdb"
    substrate_id = "01SUBSTRATE_NOEMBED01"
    _seed_substrate(db_path, substrate_id, "Some text.")

    with (
        patch(
            "oskill.translate_substrate.translate_document_async",
            new_callable=AsyncMock,
        ) as mock_td,
        patch("oskill.translate_substrate._embed_translation") as mock_embed,
    ):
        mock_td.return_value = ("译文", [_make_translate_result()])
        result = await translate_substrate(substrate_id, "zh", embed_translation=False)

    mock_embed.assert_not_called()
    assert result.embedding_ids == []


@pytest.mark.asyncio
async def test_translate_substrate_idempotent_no_overwrite(stratum_home):
    db_path = stratum_home / "meta.duckdb"
    substrate_id = "01SUBSTRATE_IDEM001"
    _seed_substrate(db_path, substrate_id, "Some text.")

    with (
        patch(
            "oskill.translate_substrate.translate_document_async",
            new_callable=AsyncMock,
        ) as mock_td,
        patch("oskill.translate_substrate._embed_translation", return_value=[]),
    ):
        mock_td.return_value = ("译文", [])
        r1 = await translate_substrate(substrate_id, "zh", provider="deepseek")
        r2 = await translate_substrate(substrate_id, "zh", provider="deepseek")

    assert r1.derivative_id == r2.derivative_id
    mock_td.assert_called_once()


@pytest.mark.asyncio
async def test_translate_substrate_not_found(stratum_schema):
    from oprim.errors import StratumError

    with pytest.raises(StratumError, match="Substrate not found"):
        await translate_substrate("NONEXISTENT_ID", "zh")


@pytest.mark.asyncio
async def test_translate_substrate_no_db(tmp_path, monkeypatch):
    import oprim._config as _cfg_mod

    monkeypatch.setenv("STRATUM_HOME", str(tmp_path / "empty_stratum"))
    _cfg_mod._store["STRATUM_HOME"] = str(tmp_path / "empty_stratum")

    from oprim.errors import StratumError

    with pytest.raises(StratumError, match="MetaDB not found"):
        await translate_substrate("ANY_ID", "zh")

    _cfg_mod._store.pop("STRATUM_HOME", None)


@pytest.mark.asyncio
async def test_translate_result_cost_aggregation(stratum_home):
    db_path = stratum_home / "meta.duckdb"
    substrate_id = "01SUBSTRATE_COST001"
    _seed_substrate(db_path, substrate_id, "Paragraph one.\n\nParagraph two.")

    chunks = [
        TranslationResult(
            text="一",
            detected_source_language="en",
            billed_characters=10,
            input_tokens=10,
            output_tokens=8,
            cost_usd=0.001,
        ),
        TranslationResult(
            text="二",
            detected_source_language="en",
            billed_characters=12,
            input_tokens=12,
            output_tokens=9,
            cost_usd=0.002,
        ),
    ]
    with (
        patch(
            "oskill.translate_substrate.translate_document_async",
            new_callable=AsyncMock,
        ) as mock_td,
        patch("oskill.translate_substrate._embed_translation", return_value=[]),
    ):
        mock_td.return_value = ("一 二", chunks)
        result = await translate_substrate(substrate_id, "zh", provider="deepseek")

    assert result.chunks_translated == 2
    assert result.total_tokens_in == 22
    assert result.total_tokens_out == 17
    assert abs(result.cost_usd - 0.003) < 1e-9
