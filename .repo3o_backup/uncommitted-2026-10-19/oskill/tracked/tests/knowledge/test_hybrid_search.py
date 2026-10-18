"""Tests for hybrid_search."""

from __future__ import annotations

from datetime import UTC
from unittest.mock import AsyncMock, patch

from oskill.hybrid_search import (
    SearchResult,
    _boost_pinned,
    _make_citation,
    _rrf_fuse,
    hybrid_search,
)


class TestRRFFuse:
    def test_rrf_combines_two_lists(self):
        list_a = [("a", 1.0), ("b", 0.8), ("c", 0.5)]
        list_b = [("b", 1.0), ("d", 0.7), ("a", 0.4)]
        result = _rrf_fuse(list_a, list_b)
        ids = [r[0] for r in result]
        assert "a" in ids
        assert "b" in ids

    def test_rrf_empty_lists(self):
        assert _rrf_fuse([], []) == []

    def test_rrf_single_list(self):
        list_a = [("x", 1.0), ("y", 0.5)]
        result = _rrf_fuse(list_a, [])
        assert result[0][0] == "x"


class TestBoostPinned:
    def test_boost_pinned_substrate(self, stratum_schema):
        from datetime import datetime

        from oprim.meta_db import open_meta_db

        from oskill.knowledge._context import meta_db_path

        now = datetime.now(UTC).isoformat()
        db = open_meta_db(meta_db_path())
        db.execute(
            "INSERT INTO substrates (id, user_id, title, mime, source_path, file_hash, "
            "byte_size, meta_json, is_pinned, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ["PINNED01", "test_user", "Pinned", "", "", "h001", 0, "{}", True, now, now],
        )
        db.execute(
            "INSERT INTO substrates (id, user_id, title, mime, source_path, file_hash, "
            "byte_size, meta_json, is_pinned, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ["NORMAL01", "test_user", "Normal", "", "", "h002", 0, "{}", False, now, now],
        )
        db.close()

        fused = [("NORMAL01", 0.02), ("PINNED01", 0.015)]  # normal ranks first before boost
        boosted = _boost_pinned(fused, boost=1.5)
        ids = [x[0] for x in boosted]
        assert ids[0] == "PINNED01"  # pinned promoted to top

    def test_boost_no_pinned(self, stratum_schema):
        fused = [("A", 0.5), ("B", 0.3)]
        boosted = _boost_pinned(fused, boost=1.5)
        assert [x[0] for x in boosted] == ["A", "B"]


class TestMakeCitation:
    def test_citation_structure(self):
        c = _make_citation("SUBID001", return_citations=True)
        assert c is not None
        assert c["substrate_id"] == "SUBID001"
        assert c["fragment_id"] == "SUBID001#0"
        assert "deep_link" in c
        assert c["deep_link"].startswith("stratum://substrate/")
        assert "anchor" in c

    def test_no_citation_when_disabled(self):
        assert _make_citation("SUBID001", return_citations=False) is None


class TestHybridSearch:
    async def test_returns_empty_when_no_indices(self, stratum_home):
        with patch("oskill.hybrid_search.embed_text", return_value=[[0.1] * 1024]):
            result = await hybrid_search("test query", corpus_id="c1")
        assert result == []

    async def test_bm25_hit(self, stratum_schema):
        from datetime import datetime

        from oprim.fulltext import open_fulltext_index
        from oprim.fulltext.tantivy import FulltextDoc
        from oprim.meta_db import open_meta_db

        from oskill.knowledge._context import meta_db_path, tantivy_path

        ft_path = tantivy_path()
        ft_path.mkdir(parents=True)
        ft_idx = open_fulltext_index(ft_path)
        ft_idx.add(
            [
                FulltextDoc(
                    id="sub001",
                    fields={
                        "title": "kelly criterion finance",
                        "content": "Kelly formula for optimal betting size",
                    },
                )
            ]
        )

        db_p = meta_db_path()
        db = open_meta_db(db_p)
        now = datetime.now(UTC).isoformat()
        db.execute(
            "INSERT INTO substrates (id, user_id, title, mime, source_path, file_hash, "
            "byte_size, meta_json, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                "sub001",
                "test_user",
                "kelly criterion finance",
                "",
                "",
                "hash001",
                0,
                '{"medium":"paper"}',
                now,
                now,
            ],
        )
        db.close()

        with patch("oskill.hybrid_search.embed_text", return_value=[[0.1] * 1024]):
            with patch("oskill.hybrid_search.open_vector_db") as mock_vdb:
                mock_vdb.return_value.search.return_value = []
                results = await hybrid_search("kelly criterion", corpus_id="c1")

        assert any(r.id == "sub001" for r in results)

    async def test_medium_filter(self, stratum_schema):
        from datetime import datetime

        from oprim.fulltext import open_fulltext_index
        from oprim.fulltext.tantivy import FulltextDoc
        from oprim.meta_db import open_meta_db

        from oskill.knowledge._context import meta_db_path, tantivy_path

        ft_path = tantivy_path()
        ft_path.mkdir(parents=True)
        ft_idx = open_fulltext_index(ft_path)
        ft_idx.add(
            [
                FulltextDoc(
                    id="paper001", fields={"title": "finance paper", "content": "finance content"}
                ),
                FulltextDoc(
                    id="book001", fields={"title": "finance book", "content": "finance content"}
                ),
            ]
        )

        db_p = meta_db_path()
        db = open_meta_db(db_p)
        now = datetime.now(UTC).isoformat()
        db.execute(
            "INSERT INTO substrates (id, user_id, title, mime, source_path, file_hash, "
            "byte_size, meta_json, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                "paper001",
                "test_user",
                "finance paper",
                "",
                "",
                "h001",
                0,
                '{"medium":"paper"}',
                now,
                now,
            ],
        )
        db.execute(
            "INSERT INTO substrates (id, user_id, title, mime, source_path, file_hash, "
            "byte_size, meta_json, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                "book001",
                "test_user",
                "finance book",
                "",
                "",
                "h002",
                0,
                '{"medium":"book"}',
                now,
                now,
            ],
        )
        db.close()

        with patch("oskill.hybrid_search.embed_text", return_value=[[0.1] * 1024]):
            with patch("oskill.hybrid_search.open_vector_db") as mock_vdb:
                mock_vdb.return_value.search.return_value = []
                results = await hybrid_search("finance", filter_medium=["paper"], corpus_id="c1")

        assert all(r.metadata.get("medium") == "paper" for r in results)

    async def test_type_filter(self, stratum_home):
        with patch("oskill.hybrid_search.embed_text", return_value=[[0.1] * 1024]):
            results = await hybrid_search("query", filter_tags=["substrate"], corpus_id="c1")
        assert all(r.type == "substrate" for r in results)

    async def test_mode_strict_does_not_call_llm(self, stratum_home):
        with patch("oskill.hybrid_search.embed_text", return_value=[[0.1] * 1024]):
            with patch("oskill.hybrid_search._llm_augmented", new=AsyncMock()) as mock_llm:
                results = await hybrid_search("no hits query", mode="strict", corpus_id="c1")
        mock_llm.assert_not_called()
        assert results == []

    async def test_mode_augmented_calls_llm_on_zero_hits(self, stratum_home):
        llm_result = SearchResult(
            type="llm_augmented",
            id="llm-0",
            title="LLM Answer",
            score=0.5,
            highlight="answer text",
            citation=None,
        )
        with patch("oskill.hybrid_search.embed_text", return_value=[[0.1] * 1024]):
            with patch(
                "oskill.hybrid_search._llm_augmented", new=AsyncMock(return_value=[llm_result])
            ):
                results = await hybrid_search("no substrate hits", mode="augmented", corpus_id="c1")
        assert len(results) == 1
        assert results[0].type == "llm_augmented"

    async def test_return_citations_true(self, stratum_schema):
        from datetime import datetime

        from oprim.fulltext import open_fulltext_index
        from oprim.fulltext.tantivy import FulltextDoc
        from oprim.meta_db import open_meta_db

        from oskill.knowledge._context import meta_db_path, tantivy_path

        ft_path = tantivy_path()
        ft_path.mkdir(parents=True)
        ft_idx = open_fulltext_index(ft_path)
        ft_idx.add(
            [
                FulltextDoc(
                    id="cite001", fields={"title": "citation test", "content": "test content"}
                )
            ]
        )

        db = open_meta_db(meta_db_path())
        now = datetime.now(UTC).isoformat()
        db.execute(
            "INSERT INTO substrates (id, user_id, title, mime, source_path, file_hash, "
            "byte_size, meta_json, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            ["cite001", "test_user", "citation test", "", "", "h001", 0, "{}", now, now],
        )
        db.close()

        with patch("oskill.hybrid_search.embed_text", return_value=[[0.1] * 1024]):
            with patch("oskill.hybrid_search.open_vector_db") as mv:
                mv.return_value.search.return_value = []
                results = await hybrid_search("citation", return_citations=True, corpus_id="c1")

        assert results
        assert results[0].citation is not None
        assert "substrate_id" in results[0].citation
        assert "deep_link" in results[0].citation

    async def test_return_citations_false(self, stratum_schema):
        from datetime import datetime

        from oprim.fulltext import open_fulltext_index
        from oprim.fulltext.tantivy import FulltextDoc
        from oprim.meta_db import open_meta_db

        from oskill.knowledge._context import meta_db_path, tantivy_path

        ft_path = tantivy_path()
        ft_path.mkdir(parents=True)
        ft_idx = open_fulltext_index(ft_path)
        ft_idx.add(
            [FulltextDoc(id="nocite001", fields={"title": "no citation", "content": "content"})]
        )

        db = open_meta_db(meta_db_path())
        now = datetime.now(UTC).isoformat()
        db.execute(
            "INSERT INTO substrates (id, user_id, title, mime, source_path, file_hash, "
            "byte_size, meta_json, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            ["nocite001", "test_user", "no citation", "", "", "h001", 0, "{}", now, now],
        )
        db.close()

        with patch("oskill.hybrid_search.embed_text", return_value=[[0.1] * 1024]):
            with patch("oskill.hybrid_search.open_vector_db") as mv:
                mv.return_value.search.return_value = []
                results = await hybrid_search("citation", return_citations=False, corpus_id="c1")

        assert results
        assert results[0].citation is None

    async def test_pinned_boost_promotes_pinned(self, stratum_schema):
        from datetime import datetime

        from oprim.fulltext import open_fulltext_index
        from oprim.fulltext.tantivy import FulltextDoc
        from oprim.meta_db import open_meta_db

        from oskill.knowledge._context import meta_db_path, tantivy_path

        ft_path = tantivy_path()
        ft_path.mkdir(parents=True)
        ft_idx = open_fulltext_index(ft_path)
        ft_idx.add(
            [
                FulltextDoc(
                    id="normal_a",
                    fields={"title": "finance content", "content": "finance normal text"},
                ),
                FulltextDoc(
                    id="pinned_b",
                    fields={"title": "finance content", "content": "finance pinned text"},
                ),
            ]
        )

        db = open_meta_db(meta_db_path())
        now = datetime.now(UTC).isoformat()
        db.execute(
            "INSERT INTO substrates (id, user_id, title, mime, source_path, file_hash, "
            "byte_size, meta_json, is_pinned, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ["normal_a", "test_user", "Finance Normal", "", "", "h001", 0, "{}", False, now, now],
        )
        db.execute(
            "INSERT INTO substrates (id, user_id, title, mime, source_path, file_hash, "
            "byte_size, meta_json, is_pinned, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ["pinned_b", "test_user", "Finance Pinned", "", "", "h002", 0, "{}", True, now, now],
        )
        db.close()

        with patch("oskill.hybrid_search.embed_text", return_value=[[0.1] * 1024]):
            with patch("oskill.hybrid_search.open_vector_db") as mv:
                mv.return_value.search.return_value = []
                results = await hybrid_search("finance", pinned_boost=2.0, corpus_id="c1")

        pinned_idx = next((i for i, r in enumerate(results) if r.id == "pinned_b"), None)
        normal_idx = next((i for i, r in enumerate(results) if r.id == "normal_a"), None)
        assert pinned_idx is not None and normal_idx is not None
        assert pinned_idx < normal_idx  # pinned ranked higher

    async def test_view_id_accepted_without_error(self, stratum_home):
        with patch("oskill.hybrid_search.embed_text", return_value=[[0.1] * 1024]):
            result = await hybrid_search("test", view_id="some-view-id", corpus_id="c1")
        assert isinstance(result, list)

    async def test_unknown_view_id_no_crash(self, stratum_schema):
        """Unknown view_id returns empty filter — search proceeds normally."""
        with patch("oskill.hybrid_search.embed_text", return_value=[[0.1] * 1024]):
            result = await hybrid_search("test", view_id="nonexistent-uuid", corpus_id="c1")
        assert isinstance(result, list)


class TestViewFilterResolution:
    """Phase 13 — view_id and user_id default view filter application."""

    def _insert_substrate(
        self, db, sid: str, medium: str, domain: str | None = None, created_at: str | None = None
    ) -> None:
        from datetime import datetime

        now = created_at or datetime.now(UTC).isoformat()
        meta = {"medium": medium}
        if domain:
            meta["domain"] = domain
        import json

        db.execute(
            "INSERT INTO substrates (id, user_id, title, mime, source_path, file_hash, "
            "byte_size, meta_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                sid,
                "test_user",
                f"title-{sid}",
                "",
                "",
                f"hash-{sid}",
                0,
                json.dumps(meta),
                now,
                now,
            ],
        )

    def _insert_view(
        self, db, view_id: str, user_id: str, default_filter: dict, is_default: bool = False
    ) -> None:
        import json
        from datetime import datetime

        now = datetime.now(UTC).isoformat()
        db.execute(
            "INSERT INTO views (id, user_id, name, description, default_filter, "
            "default_llm, default_system_prompt, icon, is_default, is_builtin, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                view_id,
                user_id,
                "TestView",
                None,
                json.dumps(default_filter),
                "{}",
                None,
                None,
                is_default,
                False,
                now,
                now,
            ],
        )

    async def test_view_id_applies_medium_filter(self, stratum_schema):
        from oprim.fulltext import open_fulltext_index
        from oprim.fulltext.tantivy import FulltextDoc
        from oprim.meta_db import open_meta_db

        from oskill.knowledge._context import meta_db_path, tantivy_path

        ft_idx = open_fulltext_index(tantivy_path())
        ft_idx.add(
            [
                FulltextDoc(id="p001", fields={"title": "finance paper", "content": "quant"}),
                FulltextDoc(id="n001", fields={"title": "finance note", "content": "quant"}),
            ]
        )
        db = open_meta_db(meta_db_path())
        self._insert_substrate(db, "p001", "paper")
        self._insert_substrate(db, "n001", "note")
        self._insert_view(db, "v-paper", "u1", {"medium": ["paper"]})
        db.close()

        with patch("oskill.hybrid_search.embed_text", return_value=[[0.1] * 1024]):
            with patch("oskill.hybrid_search.open_vector_db") as mv:
                mv.return_value.search.return_value = []
                results = await hybrid_search("finance", view_id="v-paper", corpus_id="c1")

        assert all(r.metadata.get("medium") == "paper" for r in results)
        ids = {r.id for r in results}
        assert "p001" in ids
        assert "n001" not in ids

    async def test_explicit_medium_filter_overrides_view(self, stratum_schema):
        from oprim.fulltext import open_fulltext_index
        from oprim.fulltext.tantivy import FulltextDoc
        from oprim.meta_db import open_meta_db

        from oskill.knowledge._context import meta_db_path, tantivy_path

        ft_idx = open_fulltext_index(tantivy_path())
        ft_idx.add(
            [
                FulltextDoc(id="pa002", fields={"title": "strategy paper", "content": "trade"}),
                FulltextDoc(id="bk002", fields={"title": "strategy book", "content": "trade"}),
            ]
        )
        db = open_meta_db(meta_db_path())
        self._insert_substrate(db, "pa002", "paper")
        self._insert_substrate(db, "bk002", "book")
        self._insert_view(db, "v-paper2", "u3", {"medium": ["paper"]})
        db.close()

        with patch("oskill.hybrid_search.embed_text", return_value=[[0.1] * 1024]):
            with patch("oskill.hybrid_search.open_vector_db") as mv:
                mv.return_value.search.return_value = []
                # caller passes filter_medium=["book"] — should override view's ["paper"]
                results = await hybrid_search(
                    "strategy", view_id="v-paper2", filter_medium=["book"], corpus_id="c1"
                )

        assert all(r.metadata.get("medium") == "book" for r in results)

    async def test_domain_filter_excludes_tagged_mismatch(self, stratum_schema):
        from oprim.fulltext import open_fulltext_index
        from oprim.fulltext.tantivy import FulltextDoc
        from oprim.meta_db import open_meta_db

        from oskill.knowledge._context import meta_db_path, tantivy_path

        ft_idx = open_fulltext_index(tantivy_path())
        ft_idx.add(
            [
                FulltextDoc(id="q001", fields={"title": "quant paper", "content": "sharpe ratio"}),
                FulltextDoc(id="lit001", fields={"title": "poem", "content": "sharpe ratio"}),
            ]
        )
        db = open_meta_db(meta_db_path())
        self._insert_substrate(db, "q001", "paper", domain="quant")
        self._insert_substrate(db, "lit001", "article", domain="literature")
        db.close()

        with patch("oskill.hybrid_search.embed_text", return_value=[[0.1] * 1024]):
            with patch("oskill.hybrid_search.open_vector_db") as mv:
                mv.return_value.search.return_value = []
                results = await hybrid_search(
                    "sharpe ratio", filter_tags=["quant", "finance"], corpus_id="c1"
                )

        ids = {r.id for r in results}
        assert "q001" in ids
        assert "lit001" not in ids

    async def test_domain_filter_passes_untagged(self, stratum_schema):
        """Substrates without domain tag pass through the domain filter."""
        from oprim.fulltext import open_fulltext_index
        from oprim.fulltext.tantivy import FulltextDoc
        from oprim.meta_db import open_meta_db

        from oskill.knowledge._context import meta_db_path, tantivy_path

        ft_idx = open_fulltext_index(tantivy_path())
        ft_idx.add(
            [FulltextDoc(id="nd001", fields={"title": "general content", "content": "test"})]
        )
        db = open_meta_db(meta_db_path())
        self._insert_substrate(db, "nd001", "paper")  # no domain
        db.close()

        with patch("oskill.hybrid_search.embed_text", return_value=[[0.1] * 1024]):
            with patch("oskill.hybrid_search.open_vector_db") as mv:
                mv.return_value.search.return_value = []
                results = await hybrid_search("general", filter_tags=["quant"], corpus_id="c1")

        assert any(r.id == "nd001" for r in results)
