"""Tests for oskill-001 and oskill-002: cross_layer_search and recommend_content."""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime

# Stub the oskill package entry-point so __init__.py (which pulls in oprim/alembic)
# is never executed. The individual submodules are pure-Python and load fine.
if "oskill" not in sys.modules:
    _oskill_stub = types.ModuleType("oskill")
    _oskill_stub.__path__ = [str(__file__).replace("tests/test_stratum_b2_group_b.py", "oskill")]
    _oskill_stub.__package__ = "oskill"
    sys.modules["oskill"] = _oskill_stub

import pytest

from oskill._exceptions import OskillError
from oskill.cross_layer_search import (
    CrossLayerSearchResult,
    cross_layer_search,
)
from oskill.recommend_content import (
    ContentMeta,
    Recommendation,
    UserBehaviorProfile,
    recommend_content,
)

# ---------------------------------------------------------------------------
# Helpers / mock callables
# ---------------------------------------------------------------------------


def mock_tantivy_empty(*, query, top_k, filters=None):
    return []


def mock_lancedb_empty(*, query_embedding, query, top_k, filters=None):
    return []


def mock_tantivy_one(*, query, top_k, filters=None):
    return [{"id": "s1", "type": "user_substrate", "title": "Test", "highlight": "abc"}]


def mock_lancedb_one(*, query_embedding, query, top_k, filters=None):
    return [{"id": "l1", "type": "user_substrate", "title": "Lance", "highlight": "xyz"}]


def mock_lancedb_pinned(*, query_embedding, query, top_k, filters=None):
    return [
        {
            "id": "pinned1",
            "type": "user_substrate",
            "title": "Pinned",
            "highlight": "p",
            "is_pinned": True,
        },
        {"id": "normal1", "type": "user_substrate", "title": "Normal", "highlight": "n"},
    ]


def mock_pgvector_one(*, query_embedding, top_k, filters=None):
    return [{"id": "p1", "type": "platform_content", "title": "Platform", "highlight": "plat"}]


# ---------------------------------------------------------------------------
# cross_layer_search tests
# ---------------------------------------------------------------------------


class TestCrossLayerSearch:
    def test_empty_query_raises(self):
        with pytest.raises(OskillError, match="query cannot be empty"):
            cross_layer_search(
                query="   ",
                tantivy_mgr=mock_tantivy_empty,
                lancedb_mgr=mock_lancedb_empty,
            )

    def test_scope_user_substrate_only_pgvector_never_called(self):
        pgvector_called = []

        def tracking_pgvector(*, query_embedding, top_k, filters=None):
            pgvector_called.append(True)
            return []

        cross_layer_search(
            query="hello",
            scope=["user_substrate"],
            tantivy_mgr=mock_tantivy_one,
            lancedb_mgr=mock_lancedb_one,
            pgvector_mgr=tracking_pgvector,
        )
        assert pgvector_called == [], (
            "pgvector_mgr must not be called when platform_content not in scope"
        )

    def test_pgvector_none_with_platform_content_in_scope_no_error(self):
        result = cross_layer_search(
            query="hello",
            scope=["platform_content"],
            tantivy_mgr=mock_tantivy_empty,
            lancedb_mgr=mock_lancedb_empty,
            pgvector_mgr=None,
        )
        assert isinstance(result, CrossLayerSearchResult)
        assert result.scope_hit_counts.get("platform_content") == 0

    def test_pinned_item_ranks_higher(self):
        # lancedb returns pinned item first; tantivy returns same id without pin.
        # The pinned boost should give the pinned item a higher RRF score.
        def tantivy_unpinned(*, query, top_k, filters=None):
            return [
                {"id": "normal1", "type": "user_substrate", "title": "Normal", "highlight": "n"},
                {"id": "pinned1", "type": "user_substrate", "title": "Pinned", "highlight": "p"},
            ]

        result = cross_layer_search(
            query="test",
            scope=["user_substrate"],
            tantivy_mgr=tantivy_unpinned,
            lancedb_mgr=mock_lancedb_pinned,
            pinned_boost=2.0,
        )
        ids = [r.id for r in result.results]
        assert "pinned1" in ids
        assert "normal1" in ids
        pinned_score = next(r.score for r in result.results if r.id == "pinned1")
        normal_score = next(r.score for r in result.results if r.id == "normal1")
        assert pinned_score > normal_score

    def test_empty_results_from_all_managers(self):
        result = cross_layer_search(
            query="nothing",
            tantivy_mgr=mock_tantivy_empty,
            lancedb_mgr=mock_lancedb_empty,
        )
        assert result.results == []
        assert result.citations == []

    def test_results_sorted_by_score_descending(self):
        def tantivy_multi(*, query, top_k, filters=None):
            return [
                {"id": "a", "type": "user_substrate", "title": "A", "highlight": ""},
                {"id": "b", "type": "user_substrate", "title": "B", "highlight": ""},
                {"id": "c", "type": "user_substrate", "title": "C", "highlight": ""},
            ]

        def lancedb_multi(*, query_embedding, query, top_k, filters=None):
            return [
                {
                    "id": "b",
                    "type": "user_substrate",
                    "title": "B",
                    "highlight": "",
                    "is_pinned": True,
                },
                {"id": "d", "type": "user_substrate", "title": "D", "highlight": ""},
            ]

        result = cross_layer_search(
            query="sort test",
            tantivy_mgr=tantivy_multi,
            lancedb_mgr=lancedb_multi,
        )
        scores = [r.score for r in result.results]
        assert scores == sorted(scores, reverse=True)

    def test_search_time_ms_is_non_negative_int(self):
        result = cross_layer_search(
            query="timing",
            tantivy_mgr=mock_tantivy_one,
            lancedb_mgr=mock_lancedb_one,
        )
        assert isinstance(result.search_time_ms, int)
        assert result.search_time_ms >= 0

    def test_pgvector_results_included_when_provided(self):
        result = cross_layer_search(
            query="platform search",
            scope=["platform_content"],
            tantivy_mgr=mock_tantivy_empty,
            lancedb_mgr=mock_lancedb_empty,
            pgvector_mgr=mock_pgvector_one,
        )
        assert any(r.id == "p1" for r in result.results)
        assert result.scope_hit_counts.get("platform_content") == 1


# ---------------------------------------------------------------------------
# recommend_content tests
# ---------------------------------------------------------------------------


def _make_content(
    cid: str,
    days_old: float = 0.0,
    domain: list[str] | None = None,
    concepts: list[str] | None = None,
) -> ContentMeta:
    from datetime import timedelta

    pub = datetime.now(UTC) - timedelta(days=days_old)
    return ContentMeta(
        content_id=cid,
        title=f"Title {cid}",
        domain=domain or [],
        related_concept_ids=concepts or [],
        published_at=pub,
    )


class TestRecommendContent:
    def test_empty_pool_returns_empty(self):
        profile = UserBehaviorProfile()
        result = recommend_content(user_profile=profile, candidate_pool=[])
        assert result == []

    def test_no_behavior_sorted_by_recency(self):
        profile = UserBehaviorProfile()
        pool = [
            _make_content("old", days_old=60),
            _make_content("new", days_old=1),
            _make_content("mid", days_old=15),
        ]
        recs = recommend_content(user_profile=profile, candidate_pool=pool, top_k=3)
        ids = [r.content_id for r in recs]
        # newest first
        assert ids[0] == "new"
        assert ids[-1] == "old"

    def test_top_k_limits_results(self):
        profile = UserBehaviorProfile()
        pool = [_make_content(f"c{i}") for i in range(10)]
        recs = recommend_content(user_profile=profile, candidate_pool=pool, top_k=3)
        assert len(recs) == 3

    def test_already_viewed_excluded(self):
        profile = UserBehaviorProfile(recent_viewed=["c1", "c2"])
        pool = [_make_content("c1"), _make_content("c2"), _make_content("c3")]
        recs = recommend_content(user_profile=profile, candidate_pool=pool)
        ids = [r.content_id for r in recs]
        assert "c1" not in ids
        assert "c2" not in ids
        assert "c3" in ids

    def test_domain_overlap_increases_score(self):
        profile = UserBehaviorProfile(subscribed_domains=["AI"])
        pool = [
            _make_content("ai", domain=["AI"]),
            _make_content("sports", domain=["Sports"]),
        ]
        recs = recommend_content(user_profile=profile, candidate_pool=pool, top_k=2)
        ai_score = next(r.score for r in recs if r.content_id == "ai")
        sports_score = next(r.score for r in recs if r.content_id == "sports")
        assert ai_score > sports_score

    def test_weight_normalization_nonstandard_weights(self):
        # recency_weight + relevance_weight != 1.0 should still work fine
        profile = UserBehaviorProfile(subscribed_domains=["Tech"])
        pool = [_make_content("t1", domain=["Tech"]), _make_content("t2")]
        recs = recommend_content(
            user_profile=profile,
            candidate_pool=pool,
            top_k=2,
            recency_weight=2.0,
            relevance_weight=3.0,
        )
        assert len(recs) == 2
        scores = [r.score for r in recs]
        assert all(0.0 <= s <= 1.0 for s in scores)

    def test_all_candidates_viewed_returns_empty(self):
        profile = UserBehaviorProfile(recent_viewed=["c1", "c2", "c3"])
        pool = [_make_content("c1"), _make_content("c2"), _make_content("c3")]
        recs = recommend_content(user_profile=profile, candidate_pool=pool)
        assert recs == []

    def test_recommendation_model_fields(self):
        profile = UserBehaviorProfile()
        pool = [_make_content("x1")]
        recs = recommend_content(user_profile=profile, candidate_pool=pool, top_k=1)
        assert len(recs) == 1
        r = recs[0]
        assert isinstance(r, Recommendation)
        assert r.content_id == "x1"
        assert isinstance(r.score, float)
        assert isinstance(r.reason, str)
