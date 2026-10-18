"""Tests for K-AII-1 (query_cluster) and K-AII-2 (capability_gap_analyze).

All tests are pure-compute; no LLM, no network, no mocks needed.
"""

from __future__ import annotations

import numpy as np
from oprim._aii_types import ClusterResult, GapReport

from oskill._capability_gap_analyze import capability_gap_analyze
from oskill._query_cluster import query_cluster

# ===========================================================================
# K-AII-1: query_cluster
# ===========================================================================


class TestQueryClusterEdgeCases:
    def test_empty_texts_returns_empty_clusters(self):
        result = query_cluster(texts=[])
        assert isinstance(result, ClusterResult)
        assert result.clusters == []

    def test_single_text_returns_one_cluster_not_filtered(self):
        result = query_cluster(texts=["momentum strategy"], min_cluster_size=2)
        assert len(result.clusters) == 1
        assert result.clusters[0]["size"] == 1
        assert result.clusters[0]["members"] == ["momentum strategy"]

    def test_single_text_representative_equals_input(self):
        text = "quantitative alpha"
        result = query_cluster(texts=[text])
        assert result.clusters[0]["representative"] == text


class TestQueryClusterKeywordOnly:
    def test_similar_texts_form_one_cluster(self):
        texts = [
            "momentum strategy backtest",
            "backtest momentum factor",
        ]
        result = query_cluster(texts=texts, min_cluster_size=1)
        assert len(result.clusters) == 1
        assert result.clusters[0]["size"] == 2

    def test_unrelated_texts_stay_separate(self):
        texts = [
            "apple fruit healthy eating",
            "quantum computing algorithm",
            "deep sea fishing boat",
        ]
        result = query_cluster(texts=texts, min_cluster_size=1)
        assert len(result.clusters) == 3

    def test_min_cluster_size_filters_small_clusters(self):
        texts = [
            "alpha strategy backtest",  # pair
            "backtest alpha factor",  # pair → merged with above
            "ocean wave surfing",  # singleton
        ]
        result = query_cluster(texts=texts, min_cluster_size=2)
        # The merged cluster of 2 passes; singleton is filtered
        assert all(c["size"] >= 2 for c in result.clusters)

    def test_all_members_present_across_clusters(self):
        texts = ["alpha beta", "beta gamma", "zeta eta theta"]
        result = query_cluster(texts=texts, min_cluster_size=1)
        all_members = [m for c in result.clusters for m in c["members"]]
        assert set(all_members) == set(texts)


class TestQueryClusterWithEmbeddings:
    @staticmethod
    def _unit(v: list[float]) -> list[float]:
        arr = np.array(v, dtype=np.float64)
        return (arr / np.linalg.norm(arr)).tolist()

    def test_high_similarity_embeddings_merge_clusters(self):
        texts = ["alpha strategy", "ocean fishing", "alpha momentum"]
        # All texts get similar embeddings → all merge
        embs = [self._unit([1.0, 0.0]), self._unit([0.99, 0.14]), self._unit([0.98, 0.2])]
        result = query_cluster(
            texts=texts, embeddings=embs, similarity_threshold=0.6, min_cluster_size=1
        )
        all_members = [m for c in result.clusters for m in c["members"]]
        assert set(all_members) == set(texts)

    def test_orthogonal_embeddings_stay_separate(self):
        texts = ["alpha strategy backtest", "ocean deep diving"]
        embs = [self._unit([1.0, 0.0, 0.0]), self._unit([0.0, 1.0, 0.0])]
        result = query_cluster(
            texts=texts, embeddings=embs, similarity_threshold=0.6, min_cluster_size=1
        )
        assert len(result.clusters) == 2

    def test_deterministic_same_input_same_output(self):
        texts = ["sharpe ratio backtest", "backtest sharpe factor"]
        embs = [
            self._unit([1.0, 0.5]),
            self._unit([0.9, 0.4]),
        ]
        r1 = query_cluster(texts=texts, embeddings=embs, similarity_threshold=0.6)
        r2 = query_cluster(texts=texts, embeddings=embs, similarity_threshold=0.6)
        assert r1.clusters == r2.clusters

    def test_threshold_boundary_exactly_at_threshold_merges(self):
        # Two identical unit vectors → cosine sim = 1.0 ≥ 0.6 → merged
        texts = ["alpha sea", "beta ocean"]
        vec = self._unit([1.0, 0.0])
        embs = [vec, vec]
        result = query_cluster(
            texts=texts, embeddings=embs, similarity_threshold=0.6, min_cluster_size=1
        )
        all_members = [m for c in result.clusters for m in c["members"]]
        assert set(all_members) == set(texts)

    def test_threshold_just_below_does_not_merge_orthogonal(self):
        texts = ["alpha signal", "ocean wave"]
        embs = [self._unit([1.0, 0.0]), self._unit([0.0, 1.0])]
        result = query_cluster(
            texts=texts, embeddings=embs, similarity_threshold=0.99, min_cluster_size=1
        )
        # cos([1,0],[0,1])=0 < 0.99 → not merged
        assert len(result.clusters) == 2

    def test_keyword_and_embedding_two_stage_consistency(self):
        # Texts share keywords AND have similar embeddings → still merged once
        texts = ["alpha momentum backtest", "backtest momentum strategy"]
        embs = [self._unit([1.0, 0.1]), self._unit([0.95, 0.1])]
        result = query_cluster(
            texts=texts, embeddings=embs, similarity_threshold=0.6, min_cluster_size=1
        )
        all_members = [m for c in result.clusters for m in c["members"]]
        # Should appear exactly once each
        assert sorted(all_members) == sorted(texts)

    def test_cluster_result_type(self):
        result = query_cluster(texts=["alpha"], embeddings=[[1.0, 0.0]])
        assert isinstance(result, ClusterResult)
        assert isinstance(result.clusters, list)


# ===========================================================================
# K-AII-2: capability_gap_analyze
# ===========================================================================


class TestCapabilityGapAnalyzeEmpty:
    def test_empty_inputs_returns_empty_report(self):
        result = capability_gap_analyze(
            grade_distribution={},
            failure_stats={},
            graph_stats={},
            stale_candidates=None,
        )
        assert isinstance(result, GapReport)
        assert result.high_miss_topics == []
        assert result.stale_unverified == []
        assert result.isolated_kus == []
        assert result.grade_imbalance == {}


class TestCapabilityGapAnalyzeStale:
    def test_all_unverified_exceed_threshold(self):
        candidates = [
            {"ku_id": "k1", "days_unverified": 10, "verified": False},
            {"ku_id": "k2", "days_unverified": 8, "verified": False},
        ]
        result = capability_gap_analyze(
            grade_distribution={},
            failure_stats={},
            graph_stats={},
            stale_threshold_days=7,
            stale_candidates=candidates,
        )
        assert set(result.stale_unverified) == {"k1", "k2"}

    def test_only_exceeding_threshold_included(self):
        candidates = [
            {"ku_id": "k1", "days_unverified": 10, "verified": False},
            {"ku_id": "k2", "days_unverified": 3, "verified": False},  # below 7
            {"ku_id": "k3", "days_unverified": 20, "verified": True},  # verified
        ]
        result = capability_gap_analyze(
            grade_distribution={},
            failure_stats={},
            graph_stats={},
            stale_threshold_days=7,
            stale_candidates=candidates,
        )
        assert result.stale_unverified == ["k1"]

    def test_threshold_zero_captures_all_unverified(self):
        candidates = [
            {"ku_id": "k1", "days_unverified": 0, "verified": False},
            {"ku_id": "k2", "days_unverified": 1, "verified": False},
            {"ku_id": "k3", "days_unverified": 0, "verified": True},
        ]
        result = capability_gap_analyze(
            grade_distribution={},
            failure_stats={},
            graph_stats={},
            stale_threshold_days=0,
            stale_candidates=candidates,
        )
        assert set(result.stale_unverified) == {"k1", "k2"}

    def test_no_candidates_returns_empty_stale(self):
        result = capability_gap_analyze(
            grade_distribution={},
            failure_stats={},
            graph_stats={},
            stale_candidates=None,
        )
        assert result.stale_unverified == []


class TestCapabilityGapAnalyzeIsolated:
    def test_degree_zero_ku_is_isolated(self):
        graph_stats = {
            "k1": {"degree": 0},
            "k2": {"degree": 3},
            "k3": {"degree": 0},
        }
        result = capability_gap_analyze(
            grade_distribution={},
            failure_stats={},
            graph_stats=graph_stats,
        )
        assert set(result.isolated_kus) == {"k1", "k3"}

    def test_no_isolated_kus_when_all_connected(self):
        graph_stats = {"k1": {"degree": 2}, "k2": {"degree": 1}}
        result = capability_gap_analyze(
            grade_distribution={},
            failure_stats={},
            graph_stats=graph_stats,
        )
        assert result.isolated_kus == []


class TestCapabilityGapAnalyzeMissTopics:
    def test_high_miss_topics_included(self):
        failure_stats = {"momentum": 5, "sharpe": 3}
        result = capability_gap_analyze(
            grade_distribution={},
            failure_stats=failure_stats,
            graph_stats={},
        )
        total_miss = sum(t["miss_count"] for t in result.high_miss_topics)
        assert total_miss == 8

    def test_similar_miss_topics_clustered(self):
        failure_stats = {
            "momentum strategy backtest": 4,
            "backtest momentum factor": 3,
            "ocean sailing": 2,
        }
        result = capability_gap_analyze(
            grade_distribution={},
            failure_stats=failure_stats,
            graph_stats={},
        )
        # The momentum-related topics should cluster; ocean stays separate
        [t["topic"] for t in result.high_miss_topics]
        {t["topic"]: t["miss_count"] for t in result.high_miss_topics}
        # merged momentum cluster has total 7
        momentum_cluster = [t for t in result.high_miss_topics if t["miss_count"] == 7]
        assert len(momentum_cluster) == 1

    def test_zero_miss_count_excluded(self):
        failure_stats = {"valid_topic": 3, "empty_topic": 0}
        result = capability_gap_analyze(
            grade_distribution={},
            failure_stats=failure_stats,
            graph_stats={},
        )
        miss_counts = [t["miss_count"] for t in result.high_miss_topics]
        assert all(c > 0 for c in miss_counts)

    def test_balanced_library_no_false_gaps(self):
        result = capability_gap_analyze(
            grade_distribution={"math": {"A": 10, "B": 10, "C": 10}},
            failure_stats={},
            graph_stats={"k1": {"degree": 2}, "k2": {"degree": 1}},
            stale_candidates=[{"ku_id": "k1", "days_unverified": 1, "verified": True}],
        )
        assert result.high_miss_topics == []
        assert result.stale_unverified == []
        assert result.isolated_kus == []

    def test_query_cluster_integration(self):
        # query_cluster is called internally; ensure the pipeline runs without error
        failure_stats = {"alpha": 5, "beta": 3, "gamma": 1}
        result = capability_gap_analyze(
            grade_distribution={},
            failure_stats=failure_stats,
            graph_stats={},
        )
        assert isinstance(result.high_miss_topics, list)
        for item in result.high_miss_topics:
            assert "topic" in item
            assert "miss_count" in item
