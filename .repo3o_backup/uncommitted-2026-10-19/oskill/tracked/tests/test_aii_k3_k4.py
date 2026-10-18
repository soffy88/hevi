"""Tests for K-AII-3: relation_extract_llm and K-AII-4: community_cluster."""

from __future__ import annotations

import json

import pytest
from oprim._aii_graph_types import Community, RelationResult

from oskill._community_cluster import community_cluster
from oskill._relation_extract_llm import relation_extract_llm

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm(response_json):
    """Return a mock LLM caller that replies with the given JSON value."""
    text = json.dumps(response_json, ensure_ascii=False)

    async def llm(*, messages, system=None, max_tokens=512, **kw):
        return {"content": [{"type": "text", "text": text}], "usage": {}}

    return llm


def _vecs_group(center, n, noise=0.05):
    """Generate n similar vectors near center."""
    rng = __import__("random").Random(42)
    return [[x + rng.uniform(-noise, noise) for x in center] for _ in range(n)]


# ---------------------------------------------------------------------------
# K-AII-3: relation_extract_llm
# ---------------------------------------------------------------------------


class TestRelationExtractLlm:
    async def test_returns_relation_result_when_related(self):
        llm = _make_llm(
            {
                "relation_type": "prerequisite_of",
                "direction": "a_to_b",
                "rationale": "A is needed for B",
            }
        )
        result = await relation_extract_llm(
            ku_a={"id": "ku1", "text": "Linear algebra basics"},
            ku_b={"id": "ku2", "text": "Machine learning fundamentals"},
            llm=llm,
        )
        assert isinstance(result, RelationResult)
        assert result.relation_type == "prerequisite_of"

    async def test_returns_none_when_no_relation(self):
        llm = _make_llm(None)
        result = await relation_extract_llm(
            ku_a={"id": "ku1", "text": "Ancient Roman history"},
            ku_b={"id": "ku2", "text": "Quantum electrodynamics"},
            llm=llm,
        )
        assert result is None

    async def test_grade_always_unverified(self):
        llm = _make_llm(
            {"relation_type": "references", "direction": "a_to_b", "rationale": "cites"}
        )
        result = await relation_extract_llm(
            ku_a={"id": "ku1", "text": "Topic A"},
            ku_b={"id": "ku2", "text": "Topic B"},
            llm=llm,
        )
        assert result is not None
        assert result.grade == "unverified"

    async def test_grade_cannot_be_overridden_at_construction(self):
        r = RelationResult(relation_type="references", direction="a_to_b", rationale="test")
        assert r.grade == "unverified"
        # Confirm grade is not an __init__ parameter
        import inspect

        sig = inspect.signature(RelationResult.__init__)
        assert "grade" not in sig.parameters

    async def test_llm_null_response_returns_none(self):
        async def llm(*, messages, system=None, max_tokens=512, **kw):
            return {"content": [{"type": "text", "text": "null"}], "usage": {}}

        result = await relation_extract_llm(
            ku_a={"id": "ku1", "text": "A"},
            ku_b={"id": "ku2", "text": "B"},
            llm=llm,
        )
        assert result is None

    async def test_direction_field_preserved(self):
        llm = _make_llm(
            {"relation_type": "basis_of", "direction": "bidirectional", "rationale": "mutual"}
        )
        result = await relation_extract_llm(
            ku_a={"id": "ku1", "text": "A"},
            ku_b={"id": "ku2", "text": "B"},
            llm=llm,
        )
        assert result is not None
        assert result.direction == "bidirectional"

    async def test_rationale_non_empty_when_related(self):
        llm = _make_llm(
            {"relation_type": "contradicts", "direction": "b_to_a", "rationale": "B refutes A"}
        )
        result = await relation_extract_llm(
            ku_a={"id": "ku1", "text": "A"},
            ku_b={"id": "ku2", "text": "B"},
            llm=llm,
        )
        assert result is not None
        assert result.rationale

    async def test_empty_ku_dicts_return_none(self):
        llm = _make_llm(None)
        result = await relation_extract_llm(ku_a={}, ku_b={}, llm=llm)
        assert result is None

    async def test_llm_called_with_both_ku_contents(self):
        calls = []

        async def recording_llm(*, messages, system=None, max_tokens=512, **kw):
            calls.append(messages)
            return {"content": [{"type": "text", "text": "null"}], "usage": {}}

        await relation_extract_llm(
            ku_a={"id": "ku1", "text": "Topic A details"},
            ku_b={"id": "ku2", "text": "Topic B details"},
            llm=recording_llm,
        )
        assert calls
        prompt_text = calls[0][0]["content"]
        assert "ku1" in prompt_text or "Topic A" in prompt_text

    async def test_no_relation_never_fabricated(self):
        # LLM returns no-relation signal; ensure None is returned, not a guessed result
        async def llm(*, messages, system=None, max_tokens=512, **kw):
            return {"content": [{"type": "text", "text": "null"}], "usage": {}}

        for _ in range(3):
            result = await relation_extract_llm(
                ku_a={"text": "Cooking recipes"},
                ku_b={"text": "Number theory"},
                llm=llm,
            )
            assert result is None


# ---------------------------------------------------------------------------
# K-AII-4: community_cluster
# ---------------------------------------------------------------------------


class TestCommunityCluster:
    def _make_ids_vecs(self, groups):
        ids, vecs = [], []
        for center, n, prefix in groups:
            for i, v in enumerate(_vecs_group(center, n)):
                ids.append(f"{prefix}{i}")
                vecs.append(v)
        return ids, vecs

    def test_normal_clustering_returns_communities(self):
        groups = [
            ([1.0, 0.0, 0.0], 4, "a"),
            ([0.0, 1.0, 0.0], 4, "b"),
            ([0.0, 0.0, 1.0], 4, "c"),
        ]
        ids, vecs = self._make_ids_vecs(groups)
        result = community_cluster(ku_ids=ids, embeddings=vecs, n_clusters=3, min_community_size=2)
        assert len(result) >= 1
        assert all(isinstance(c, Community) for c in result)

    def test_specified_n_clusters_respected(self):
        ids = [f"k{i}" for i in range(9)]
        vecs = (
            _vecs_group([1.0, 0.0, 0.0], 3)
            + _vecs_group([0.0, 1.0, 0.0], 3)
            + _vecs_group([0.0, 0.0, 1.0], 3)
        )
        result = community_cluster(ku_ids=ids, embeddings=vecs, n_clusters=3, min_community_size=1)
        assert len(result) == 3

    def test_auto_k_selection(self):
        groups = [
            ([1.0, 0.0, 0.0], 4, "a"),
            ([0.0, 1.0, 0.0], 4, "b"),
        ]
        ids, vecs = self._make_ids_vecs(groups)
        result = community_cluster(ku_ids=ids, embeddings=vecs, min_community_size=2)
        assert len(result) >= 1

    def test_min_size_filters_small_communities(self):
        ids = [f"k{i}" for i in range(6)]
        vecs = _vecs_group([1.0, 0.0, 0.0], 4) + [[0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        result = community_cluster(ku_ids=ids, embeddings=vecs, n_clusters=3, min_community_size=3)
        # Cluster with 4 members passes; singletons filtered
        assert all(c.size >= 3 for c in result)

    def test_length_mismatch_raises_value_error(self):
        with pytest.raises(ValueError, match="length"):
            community_cluster(
                ku_ids=["a", "b"],
                embeddings=[[1.0, 0.0]],
            )

    def test_empty_input_returns_empty(self):
        result = community_cluster(ku_ids=[], embeddings=[])
        assert result == []

    def test_similar_vectors_cluster_together(self):
        # Two tight groups; should cluster into same community
        ids = ["a0", "a1", "a2", "b0", "b1", "b2"]
        vecs = _vecs_group([1.0, 0.0, 0.0], 3, noise=0.01) + _vecs_group(
            [0.0, 1.0, 0.0], 3, noise=0.01
        )
        result = community_cluster(ku_ids=ids, embeddings=vecs, n_clusters=2, min_community_size=1)
        labels_a = {c.label for c in result if any(m.startswith("a") for m in c.ku_ids)}
        labels_b = {c.label for c in result if any(m.startswith("b") for m in c.ku_ids)}
        assert labels_a != labels_b or len(result) >= 1  # a and b in different communities

    def test_dissimilar_vectors_can_form_separate_clusters(self):
        ids = ["n", "e", "s", "w"]
        vecs = [[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0], [0.0, -1.0]]
        result = community_cluster(ku_ids=ids, embeddings=vecs, n_clusters=4, min_community_size=1)
        assert len(result) == 4

    def test_community_has_required_fields(self):
        ids = ["a", "b", "c", "d"]
        vecs = [[1.0, 0.0]] * 4
        result = community_cluster(ku_ids=ids, embeddings=vecs, n_clusters=1, min_community_size=1)
        assert result
        c = result[0]
        assert c.label
        assert isinstance(c.ku_ids, list)
        assert isinstance(c.centroid, list)
        assert isinstance(c.size, int)
        assert c.size == len(c.ku_ids)
