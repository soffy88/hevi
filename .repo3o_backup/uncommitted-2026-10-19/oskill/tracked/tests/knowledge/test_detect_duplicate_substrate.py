"""Tests for detect_duplicate_substrate."""

from __future__ import annotations

from datetime import UTC, datetime

from oskill.knowledge.detect_duplicate_substrate import detect_duplicate_substrate


class TestDetectDuplicateSubstrate:
    async def test_no_db_returns_none(self, stratum_home):
        """No meta.duckdb → None (not an error)."""
        result = await detect_duplicate_substrate("abc123")
        assert result is None

    async def test_hash_match_returns_id(self, stratum_schema):
        """SHA-256 match → return existing substrate_id (real DuckDB, substrates table)."""
        from oprim.meta_db import open_meta_db

        from oskill.knowledge._context import meta_db_path

        db_p = meta_db_path()
        db = open_meta_db(db_p)
        now = datetime.now(UTC).isoformat()
        db.execute(
            "INSERT INTO substrates (id, user_id, title, mime, source_path, file_hash, "
            "byte_size, meta_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                "EXISTING01234567890123456",
                "test_user",
                "test",
                "",
                "",
                "deadbeef" * 8,
                0,
                '{"medium":"paper"}',
                now,
                now,
            ],
        )
        db.close()

        result = await detect_duplicate_substrate("deadbeef" * 8)
        assert result == "EXISTING01234567890123456"

    async def test_no_match_returns_none(self, stratum_schema):
        """Non-matching hash → None (real DuckDB, substrates table)."""
        result = await detect_duplicate_substrate(
            "nonexistenthashabc123456789012345678901234567890123456789012345"
        )
        assert result is None

    async def test_embedding_param_ignored_phase1(self, stratum_home):
        """Phase 1: embedding param is accepted but not used."""
        result = await detect_duplicate_substrate("abc123", embedding=[0.1] * 1024)
        assert result is None
