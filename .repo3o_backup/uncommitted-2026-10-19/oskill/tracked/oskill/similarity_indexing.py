"""B4 — Batch similarity indexing (flat + ivf)."""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

import numpy as np


def batch_similarity_indexing(
    *,
    vectors: np.ndarray,
    metadata: list[dict[str, Any]] | None = None,
    method: str = "flat",
    n_clusters: int = 16,
    persist_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build a similarity index from vectors.

    Parameters
    ----------
    vectors : ndarray of shape (n, d)
    metadata : optional list of dicts (one per vector)
    method : "flat" or "ivf"
    n_clusters : number of IVF clusters (only for method="ivf")
    persist_path : if provided, serialize index to this path

    Returns
    -------
    dict with keys: index, method, n_vectors, dimension, query_fn
    """
    if vectors.ndim != 2 or len(vectors) == 0:
        raise ValueError("vectors must be a non-empty 2D array")

    n, d = vectors.shape
    meta = metadata or [{"idx": i} for i in range(n)]

    if method == "flat":
        index_data = {"vectors": vectors, "metadata": meta}

        def query_fn(q: np.ndarray, k: int = 10) -> list[dict[str, Any]]:
            dists = np.linalg.norm(vectors - q.reshape(1, -1), axis=1)
            top_k = np.argsort(dists)[:k]
            return [{"distance": float(dists[i]), **meta[i]} for i in top_k]

    elif method == "ivf":
        from sklearn.cluster import KMeans

        km = KMeans(n_clusters=min(n_clusters, n), random_state=42, n_init=1)
        labels = km.fit_predict(vectors)
        centroids = km.cluster_centers_
        clusters: dict[int, list[int]] = {}
        for i, lbl in enumerate(labels):
            clusters.setdefault(int(lbl), []).append(i)
        index_data = {
            "vectors": vectors,
            "metadata": meta,
            "centroids": centroids,
            "clusters": clusters,
        }

        def query_fn(q: np.ndarray, k: int = 10) -> list[dict[str, Any]]:
            # Find nearest centroid, search that cluster
            c_dists = np.linalg.norm(centroids - q.reshape(1, -1), axis=1)
            nearest_c = int(np.argmin(c_dists))
            candidates = clusters[nearest_c]
            sub_vecs = vectors[candidates]
            dists = np.linalg.norm(sub_vecs - q.reshape(1, -1), axis=1)
            top_k = np.argsort(dists)[:k]
            return [{"distance": float(dists[j]), **meta[candidates[j]]} for j in top_k]
    else:
        raise ValueError(f"Unknown method: {method}")

    result = {
        "index": index_data,
        "method": method,
        "n_vectors": n,
        "dimension": d,
        "query_fn": query_fn,
    }

    if persist_path:
        p = Path(persist_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "wb") as f:
            pickle.dump(
                {"vectors": vectors, "metadata": meta, "method": method, "n_clusters": n_clusters},
                f,
            )

    return result
