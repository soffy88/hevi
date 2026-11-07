"""End-to-end test: file → ingest_substrate → hybrid_search."""

from __future__ import annotations

from unittest.mock import patch

from oskill.hybrid_search import hybrid_search
from oskill.ingest_substrate import ingest_substrate


class TestEndToEnd:
    async def test_ingest_then_search(self, stratum_schema, simple_md):
        """Gate B end-to-end: ingest a file → hybrid_search finds it."""
        with patch("oskill.ingest_substrate.embed_text", return_value=[[0.1] * 1024]):
            with patch(
                "oskill.knowledge.classify_inbox_file.detect_mime", return_value="text/markdown"
            ):
                ingest_result = await ingest_substrate(
                    simple_md, source={"type": "inbox_local"}, user_id_hash="u1"
                )

        assert ingest_result.substrate_id

        with patch("oskill.hybrid_search.embed_text", return_value=[[0.1] * 1024]):
            with patch("oskill.hybrid_search.open_vector_db") as mock_vdb:
                mock_vdb.return_value.search.return_value = []
                search_results = await hybrid_search("Test Note", corpus_id="c1")

        assert any(r.id == ingest_result.substrate_id for r in search_results), (
            f"substrate {ingest_result.substrate_id} not found in search results: {search_results}"
        )
