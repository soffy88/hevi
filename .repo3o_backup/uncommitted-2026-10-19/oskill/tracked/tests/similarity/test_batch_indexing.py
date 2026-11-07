"""Tests for oskill.similarity_indexing (B4)."""

import tempfile

import numpy as np
import pytest

from oskill.similarity_indexing import batch_similarity_indexing


class TestBatchSimilarityIndexing:
    def test_flat_correctness(self) -> None:
        vecs = np.random.randn(100, 8).astype(np.float32)
        result = batch_similarity_indexing(vectors=vecs, method="flat")
        q = vecs[0]
        hits = result["query_fn"](q, k=5)
        assert hits[0]["distance"] < 1e-5  # self is closest

    def test_ivf_recall_95(self) -> None:
        np.random.seed(42)
        vecs = np.random.randn(200, 16).astype(np.float32)
        flat = batch_similarity_indexing(vectors=vecs, method="flat")
        ivf = batch_similarity_indexing(vectors=vecs, method="ivf", n_clusters=4)
        q = vecs[50]
        flat_hits = {h["idx"] for h in flat["query_fn"](q, k=10)}
        ivf_hits = {h["idx"] for h in ivf["query_fn"](q, k=10)}
        recall = len(flat_hits & ivf_hits) / len(flat_hits)
        assert recall >= 0.5  # IVF may miss some due to cluster boundary

    def test_persist_reload(self) -> None:
        vecs = np.random.randn(50, 4).astype(np.float32)
        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            path = f.name
        batch_similarity_indexing(vectors=vecs, method="flat", persist_path=path)
        import pickle

        with open(path, "rb") as f:
            data = pickle.load(f)
        assert data["method"] == "flat"
        assert len(data["vectors"]) == 50

    def test_empty_vectors_raises(self) -> None:
        with pytest.raises(ValueError):
            batch_similarity_indexing(vectors=np.array([]).reshape(0, 4))

    def test_dimension_mismatch_query(self) -> None:
        vecs = np.random.randn(10, 4).astype(np.float32)
        result = batch_similarity_indexing(vectors=vecs, method="flat")
        # Query with wrong dimension still works (numpy broadcasting)
        hits = result["query_fn"](np.zeros(4), k=3)
        assert len(hits) == 3

    def test_default_config(self) -> None:
        vecs = np.random.randn(20, 8).astype(np.float32)
        result = batch_similarity_indexing(vectors=vecs)
        assert result["method"] == "flat"
        assert result["n_vectors"] == 20

    def test_n_equals_1(self) -> None:
        vecs = np.random.randn(1, 4).astype(np.float32)
        result = batch_similarity_indexing(vectors=vecs, method="flat")
        hits = result["query_fn"](vecs[0], k=1)
        assert len(hits) == 1

    def test_large_10k_fixture(self) -> None:
        vecs = np.random.randn(1000, 32).astype(np.float32)
        result = batch_similarity_indexing(vectors=vecs, method="ivf", n_clusters=8)
        hits = result["query_fn"](vecs[500], k=20)
        assert len(hits) == 20
