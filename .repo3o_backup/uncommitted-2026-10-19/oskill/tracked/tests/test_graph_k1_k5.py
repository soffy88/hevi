"""Tests for K-G1 through K-G5 graph skills."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from oprim._aii_graph_types import ConflictPair

from oskill._cascade_delete import cascade_delete
from oskill._conflict_resolution import conflict_resolution
from oskill._graph_expand_retrieval import graph_expand_retrieval
from oskill._relevance_compute import relevance_compute
from oskill._two_step_ingest import two_step_ingest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _vec_same(dim=4):
    return [1.0] + [0.0] * (dim - 1)


def _vec_near(dim=4):
    return [0.999] + [0.001] * (dim - 1)


def _make_llm(payload):
    text = json.dumps(payload, ensure_ascii=False)

    async def llm(*, messages, system=None, max_tokens=256, **kw):
        return {"content": [{"type": "text", "text": text}], "usage": {}}

    return llm


def _make_db(neighbors_map=None, data_map=None, source_ku_map=None, ku_source_map=None):
    db = MagicMock()
    db.get_neighbors = MagicMock(side_effect=lambda ku: (neighbors_map or {}).get(ku, []))
    db.get_ku_data = MagicMock(side_effect=lambda ku: (data_map or {}).get(ku, {}))
    db.get_ku_ids_for_source = MagicMock(side_effect=lambda src: (source_ku_map or {}).get(src, []))
    db.get_source_ids_for_ku = MagicMock(side_effect=lambda ku: (ku_source_map or {}).get(ku, []))
    db.get_dangling_deps_count = MagicMock(return_value=0)
    db.clear_dangling_deps = MagicMock()
    db.delete_ku = MagicMock()
    return db


# ---------------------------------------------------------------------------
# K-G1: conflict_resolution
# ---------------------------------------------------------------------------


class TestConflictResolution:
    async def test_genuine_conflict_returns_pair(self):
        llm = _make_llm(
            {
                "conflict_type": "factual_contradiction",
                "description": "A and B contradict",
                "severity": "high",
            }
        )
        result = await conflict_resolution(
            new_ku_texts=["该药物增加血压"],
            new_ku_embeddings=[[1.0, 0.0, 0.0, 0.0]],
            existing_ku_texts=["该药物减少血压"],
            existing_ku_embeddings=[[0.999, 0.001, 0.0, 0.0]],
            existing_ku_ids=["ku_exist_1"],
            llm=llm,
            conflict_threshold=0.5,
        )
        assert len(result) == 1
        assert result[0].conflict_type == "factual_contradiction"
        assert result[0].existing_ku_id == "ku_exist_1"

    async def test_no_conflict_returns_empty(self):
        llm = _make_llm(None)
        result = await conflict_resolution(
            new_ku_texts=["机器学习算法"],
            new_ku_embeddings=[[1.0, 0.0, 0.0, 0.0]],
            existing_ku_texts=["量子力学原理"],
            existing_ku_embeddings=[[0.0, 1.0, 0.0, 0.0]],
            existing_ku_ids=["ku_exist_2"],
            llm=llm,
            conflict_threshold=0.5,
        )
        assert result == []

    async def test_grade_always_unverified(self):
        llm = _make_llm(
            {"conflict_type": "stance_opposition", "description": "opposing", "severity": "medium"}
        )
        result = await conflict_resolution(
            new_ku_texts=["支持该政策"],
            new_ku_embeddings=[[1.0, 0.0, 0.0, 0.0]],
            existing_ku_texts=["反对该政策"],
            existing_ku_embeddings=[[0.999, 0.001, 0.0, 0.0]],
            existing_ku_ids=["ku_exist_3"],
            llm=llm,
            conflict_threshold=0.5,
        )
        assert result
        assert all(p.grade == "unverified" for p in result)

    async def test_grade_not_in_init_signature(self):
        import inspect

        sig = inspect.signature(ConflictPair.__init__)
        assert "grade" not in sig.parameters

    async def test_low_similarity_skips_llm(self):
        call_count = [0]

        async def counting_llm(*, messages, **kw):
            call_count[0] += 1
            return {"content": [{"type": "text", "text": "null"}], "usage": {}}

        await conflict_resolution(
            new_ku_texts=["completely unrelated A"],
            new_ku_embeddings=[[1.0, 0.0, 0.0, 0.0]],
            existing_ku_texts=["completely unrelated B"],
            existing_ku_embeddings=[[0.0, 1.0, 0.0, 0.0]],
            existing_ku_ids=["ku_x"],
            llm=counting_llm,
            conflict_threshold=0.5,
        )
        assert call_count[0] == 0  # LLM not called when similarity low

    async def test_llm_null_no_fabrication(self):
        llm = _make_llm(None)
        result = await conflict_resolution(
            new_ku_texts=["增加效率"],
            new_ku_embeddings=[[1.0, 0.0, 0.0, 0.0]],
            existing_ku_texts=["减少消耗"],
            existing_ku_embeddings=[[0.999, 0.001, 0.0, 0.0]],
            existing_ku_ids=["ku_y"],
            llm=llm,
            conflict_threshold=0.5,
        )
        assert result == []

    async def test_new_ku_idx_correct(self):
        llm = _make_llm(
            {"conflict_type": "factual_contradiction", "description": "x", "severity": "low"}
        )
        result = await conflict_resolution(
            new_ku_texts=["A不conflict", "B增加C减少"],
            new_ku_embeddings=[[0.0, 1.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0]],
            existing_ku_texts=["B减少C增加"],
            existing_ku_embeddings=[[0.999, 0.001, 0.0, 0.0]],
            existing_ku_ids=["ku_z"],
            llm=llm,
            conflict_threshold=0.5,
        )
        # Only second new KU (idx=1) has high similarity
        for pair in result:
            assert pair.new_ku_idx == 1

    async def test_severity_preserved(self):
        llm = _make_llm(
            {"conflict_type": "scope_conflict", "description": "scope", "severity": "medium"}
        )
        result = await conflict_resolution(
            new_ku_texts=["促进代谢"],
            new_ku_embeddings=[[1.0, 0.0, 0.0, 0.0]],
            existing_ku_texts=["抑制代谢"],
            existing_ku_embeddings=[[0.999, 0.001, 0.0, 0.0]],
            existing_ku_ids=["ku_s"],
            llm=llm,
            conflict_threshold=0.5,
        )
        if result:
            assert result[0].severity == "medium"


# ---------------------------------------------------------------------------
# K-G2: two_step_ingest
# ---------------------------------------------------------------------------


class TestTwoStepIngest:
    def _make_step_llm(self, step1_data, step2_data):
        call_count = [0]

        async def llm(*, messages, system=None, max_tokens=1024, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"content": [{"type": "text", "text": json.dumps(step1_data)}], "usage": {}}
            return {"content": [{"type": "text", "text": json.dumps(step2_data)}], "usage": {}}

        return llm

    async def test_returns_two_step_result(self):
        s1 = {
            "entities": ["E1"],
            "concepts": ["C1"],
            "conflict_candidates": [],
            "structure": "linear",
        }
        s2 = {
            "ku_candidates": [
                {"title": "KU1", "content": "content", "type": "theorem", "confidence": "high"}
            ]
        }
        result = await two_step_ingest(
            source_text="Some mathematical theorem about convergence.",
            existing_ku_summaries=["Theorem about divergence"],
            llm=self._make_step_llm(s1, s2),
        )
        assert result.analysis == s1
        assert len(result.ku_candidates) == 1
        assert result.ku_candidates[0]["title"] == "KU1"

    async def test_two_llm_calls_made(self):
        calls = []

        async def counting_llm(*, messages, system=None, max_tokens=1024, **kw):
            calls.append(messages[0]["content"])
            return {"content": [{"type": "text", "text": "{}"}], "usage": {}}

        await two_step_ingest(
            source_text="text",
            existing_ku_summaries=[],
            llm=counting_llm,
        )
        assert len(calls) == 2

    async def test_step2_prompt_contains_step1_analysis(self):
        calls = []
        s1 = {
            "entities": ["UniqueEntity999"],
            "concepts": [],
            "conflict_candidates": [],
            "structure": "",
        }

        async def recording_llm(*, messages, system=None, max_tokens=1024, **kw):
            calls.append(messages[0]["content"])
            if len(calls) == 1:
                return {"content": [{"type": "text", "text": json.dumps(s1)}], "usage": {}}
            return {"content": [{"type": "text", "text": "{}"}], "usage": {}}

        await two_step_ingest(source_text="text", existing_ku_summaries=[], llm=recording_llm)
        assert len(calls) == 2
        assert "UniqueEntity999" in calls[1]  # Step 1 result in Step 2 prompt

    async def test_conflict_candidates_are_candidates_not_confirmed(self):
        s1 = {
            "entities": [],
            "concepts": [],
            "conflict_candidates": ["possible conflict with X"],
            "structure": "",
        }
        s2 = {"ku_candidates": []}
        result = await two_step_ingest(
            source_text="text", existing_ku_summaries=[], llm=self._make_step_llm(s1, s2)
        )
        assert "possible conflict with X" in result.conflict_candidates
        # No confirmed conflict — conflict_candidates are candidates only

    async def test_no_existing_summaries_works(self):
        s1 = {"entities": [], "concepts": [], "conflict_candidates": [], "structure": ""}
        s2 = {"ku_candidates": []}
        result = await two_step_ingest(
            source_text="text", existing_ku_summaries=[], llm=self._make_step_llm(s1, s2)
        )
        assert isinstance(result.analysis, dict)

    async def test_llm_failure_returns_empty_defaults(self):
        async def failing_llm(*, messages, **kw):
            return {"content": [{"type": "text", "text": "not json"}], "usage": {}}

        result = await two_step_ingest(
            source_text="text", existing_ku_summaries=[], llm=failing_llm
        )
        assert isinstance(result.ku_candidates, list)
        assert isinstance(result.conflict_candidates, list)

    async def test_ku_candidates_are_dicts(self):
        s1 = {"entities": [], "concepts": [], "conflict_candidates": [], "structure": ""}
        s2 = {
            "ku_candidates": [{"title": "T", "content": "C", "type": "claim", "confidence": "low"}]
        }
        result = await two_step_ingest(
            source_text="t", existing_ku_summaries=[], llm=self._make_step_llm(s1, s2)
        )
        assert all(isinstance(k, dict) for k in result.ku_candidates)

    async def test_multiple_existing_summaries_in_step1(self):
        calls = []

        async def recording_llm(*, messages, system=None, max_tokens=1024, **kw):
            calls.append(messages[0]["content"])
            return {"content": [{"type": "text", "text": "{}"}], "usage": {}}

        await two_step_ingest(
            source_text="t", existing_ku_summaries=["s1", "s2", "s3"], llm=recording_llm
        )
        assert "s1" in calls[0] and "s2" in calls[0]


# ---------------------------------------------------------------------------
# K-G3: relevance_compute
# ---------------------------------------------------------------------------


class TestRelevanceCompute:
    def _base_args(self, **overrides):
        args = dict(
            ku_id_a="a",
            ku_id_b="b",
            edges=[],
            sources_a=[],
            sources_b=[],
            neighbors_a=[],
            neighbors_b=[],
            neighbor_degree={},
            type_a="theorem",
            type_b="theorem",
        )
        args.update(overrides)
        return args

    def test_all_zero_signals_returns_type_affinity_only(self):
        score = relevance_compute(**self._base_args())
        # direct=0, source=0, adamic=0, type=1.0 (same type)
        assert score == 1.0

    def test_direct_edge_contributes(self):
        edges = [{"source": "a", "target": "b"}]
        score = relevance_compute(**self._base_args(edges=edges))
        assert score > 1.0  # type affinity (1.0) + direct (3.0)

    def test_source_overlap_contributes(self):
        score = relevance_compute(**self._base_args(sources_a=["s1"], sources_b=["s1"]))
        # source = 4.0, type = 1.0 (same type)
        assert score == 5.0

    def test_weight_injection_scales_score(self):
        score_w1 = relevance_compute(**self._base_args())
        score_w2 = relevance_compute(**self._base_args(weights={"type": 2.0}))
        assert score_w2 == score_w1 * 2.0

    def test_custom_weights_partial_merge(self):
        # Only override 'direct', others remain default
        edges = [{"source": "a", "target": "b"}]
        score = relevance_compute(**self._base_args(edges=edges, weights={"direct": 0.0}))
        # direct contribution removed: 0*3 + 0*0 + 0*0 + 1*1 = 1.0
        assert score == 1.0


# ---------------------------------------------------------------------------
# K-G4: graph_expand_retrieval
# ---------------------------------------------------------------------------


class TestGraphExpandRetrieval:
    def _simple_db(self, adj: dict[str, list[str]], data: dict[str, dict] | None = None):
        db = MagicMock()
        db.get_neighbors = MagicMock(side_effect=lambda ku: adj.get(ku, []))
        db.get_ku_data = MagicMock(side_effect=lambda ku: (data or {}).get(ku, {}))
        return db

    def _relevance_fn(self, score: float = 1.0):
        def fn(**kw):
            return score

        return fn

    async def test_single_hop_returns_neighbors(self):
        db = self._simple_db({"seed": ["n1", "n2"]})
        result = await graph_expand_retrieval(
            seed_ku_ids=["seed"],
            query_embedding=[1.0, 0.0],
            max_hops=1,
            max_results=10,
            db_conn=db,
            relevance_fn=self._relevance_fn(2.0),
        )
        ku_ids = {r.ku_id for r in result}
        assert "n1" in ku_ids
        assert "n2" in ku_ids

    async def test_multi_hop_expands_transitively(self):
        db = self._simple_db({"seed": ["h1"], "h1": ["h2"]})
        result = await graph_expand_retrieval(
            seed_ku_ids=["seed"],
            query_embedding=[1.0, 0.0],
            max_hops=2,
            max_results=10,
            db_conn=db,
            relevance_fn=self._relevance_fn(1.0),
        )
        ku_ids = {r.ku_id for r in result}
        assert "h1" in ku_ids
        assert "h2" in ku_ids

    async def test_max_results_truncates(self):
        db = self._simple_db({"seed": [f"n{i}" for i in range(20)]})
        result = await graph_expand_retrieval(
            seed_ku_ids=["seed"],
            query_embedding=[1.0, 0.0],
            max_hops=1,
            max_results=5,
            db_conn=db,
            relevance_fn=self._relevance_fn(1.0),
        )
        assert len(result) <= 5

    async def test_empty_seed_returns_empty(self):
        db = self._simple_db({})
        result = await graph_expand_retrieval(
            seed_ku_ids=[],
            query_embedding=[1.0, 0.0],
            max_hops=2,
            max_results=10,
            db_conn=db,
            relevance_fn=self._relevance_fn(1.0),
        )
        assert result == []

    async def test_cycle_handled_no_infinite_loop(self):
        # A → B → A (cycle)
        db = self._simple_db({"seed": ["A"], "A": ["B"], "B": ["A"]})
        result = await graph_expand_retrieval(
            seed_ku_ids=["seed"],
            query_embedding=[1.0],
            max_hops=3,
            max_results=10,
            db_conn=db,
            relevance_fn=self._relevance_fn(1.0),
        )
        # Should terminate without infinite loop
        ku_ids = {r.ku_id for r in result}
        assert "A" in ku_ids

    async def test_results_sorted_by_score_descending(self):
        scores = {"n1": 5.0, "n2": 1.0, "n3": 3.0}
        db = self._simple_db({"seed": ["n1", "n2", "n3"]})

        def varying_relevance(**kw):
            return scores.get(kw.get("ku_id_b", ""), 0.0)

        result = await graph_expand_retrieval(
            seed_ku_ids=["seed"],
            query_embedding=[1.0],
            max_hops=1,
            max_results=10,
            db_conn=db,
            relevance_fn=varying_relevance,
        )
        scores_out = [r.score for r in result]
        assert scores_out == sorted(scores_out, reverse=True)

    async def test_hop_distance_in_result(self):
        db = self._simple_db({"seed": ["h1"], "h1": ["h2"]})
        result = await graph_expand_retrieval(
            seed_ku_ids=["seed"],
            query_embedding=[1.0],
            max_hops=2,
            max_results=10,
            db_conn=db,
            relevance_fn=self._relevance_fn(1.0),
        )
        hops = {r.ku_id: r.hop_distance for r in result}
        assert hops.get("h1") == 1
        assert hops.get("h2") == 2

    async def test_retrieval_path_traces_from_seed(self):
        db = self._simple_db({"seed": ["mid"], "mid": ["leaf"]})
        result = await graph_expand_retrieval(
            seed_ku_ids=["seed"],
            query_embedding=[1.0],
            max_hops=2,
            max_results=10,
            db_conn=db,
            relevance_fn=self._relevance_fn(1.0),
        )
        leaf_result = next((r for r in result if r.ku_id == "leaf"), None)
        assert leaf_result is not None
        assert "seed" in leaf_result.retrieval_path


# ---------------------------------------------------------------------------
# K-G5: cascade_delete
# ---------------------------------------------------------------------------


class TestCascadeDelete:
    async def test_dry_run_does_not_delete(self):
        db = _make_db(
            source_ku_map={"src1": ["ku1", "ku2"]},
            ku_source_map={"ku1": ["src1"], "ku2": ["src1"]},
        )
        result = await cascade_delete(source_id="src1", db_conn=db, dry_run=True)
        assert result.dry_run is True
        assert "ku1" in result.deleted_ku_ids
        assert "ku2" in result.deleted_ku_ids
        db.delete_ku.assert_not_called()

    async def test_exclusive_ku_marked_for_deletion(self):
        db = _make_db(
            source_ku_map={"src1": ["ku1"]},
            ku_source_map={"ku1": ["src1"]},
        )
        result = await cascade_delete(source_id="src1", db_conn=db, dry_run=True)
        assert "ku1" in result.deleted_ku_ids
        assert result.preserved_ku_ids == []

    async def test_shared_ku_preserved(self):
        db = _make_db(
            source_ku_map={"src1": ["ku1", "ku2"]},
            ku_source_map={"ku1": ["src1", "src2"], "ku2": ["src1"]},
        )
        result = await cascade_delete(source_id="src1", db_conn=db, dry_run=True)
        assert "ku1" in result.preserved_ku_ids
        assert "ku2" in result.deleted_ku_ids

    async def test_actual_delete_when_dry_run_false(self):
        db = _make_db(
            source_ku_map={"src1": ["ku1"]},
            ku_source_map={"ku1": ["src1"]},
        )
        result = await cascade_delete(source_id="src1", db_conn=db, dry_run=False)
        assert result.dry_run is False
        db.delete_ku.assert_called_once_with("ku1")

    async def test_dangling_deps_counted(self):
        db = _make_db(
            source_ku_map={"src1": ["ku1"]},
            ku_source_map={"ku1": ["src1"]},
        )
        db.get_dangling_deps_count = MagicMock(return_value=3)
        result = await cascade_delete(source_id="src1", db_conn=db, dry_run=True)
        assert result.dangling_deps_cleared == 3

    async def test_empty_source_returns_empty_result(self):
        db = _make_db(source_ku_map={}, ku_source_map={})
        result = await cascade_delete(source_id="nonexistent", db_conn=db)
        assert result.deleted_ku_ids == []
        assert result.preserved_ku_ids == []

    async def test_multiple_shared_all_preserved(self):
        db = _make_db(
            source_ku_map={"src1": ["k1", "k2", "k3"]},
            ku_source_map={
                "k1": ["src1", "src2"],
                "k2": ["src1", "src3"],
                "k3": ["src1", "src2", "src3"],
            },
        )
        result = await cascade_delete(source_id="src1", db_conn=db, dry_run=True)
        assert set(result.preserved_ku_ids) == {"k1", "k2", "k3"}
        assert result.deleted_ku_ids == []

    async def test_clear_dangling_called_on_real_delete(self):
        db = _make_db(
            source_ku_map={"src1": ["ku1"]},
            ku_source_map={"ku1": ["src1"]},
        )
        db.get_dangling_deps_count = MagicMock(return_value=2)
        result = await cascade_delete(source_id="src1", db_conn=db, dry_run=False)
        db.clear_dangling_deps.assert_called_once_with("ku1")
        assert result.dangling_deps_cleared == 2
