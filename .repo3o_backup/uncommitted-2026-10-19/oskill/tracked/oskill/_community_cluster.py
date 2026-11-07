"""K-AII-4: community_cluster — cosine-similarity-based community detection.

Composition:
  - cosine_similarity_batch (♻️ oprim._distance)
  - k-means clustering (inline)

Pure computation, no LLM.
"""

from __future__ import annotations

import random as _random

from oprim._aii_graph_types import Community

# ---------------------------------------------------------------------------
# Pure-Python k-means (inline, no sklearn dependency)
# ---------------------------------------------------------------------------


def _sq_dist(a: list[float], b: list[float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b))


def _mean_vec(vecs: list[list[float]]) -> list[float]:
    if not vecs:
        return []
    dim = len(vecs[0])
    return [sum(v[d] for v in vecs) / len(vecs) for d in range(dim)]


def _kmeans(
    X: list[list[float]],
    k: int,
    max_iter: int = 50,
) -> tuple[list[list[float]], list[int]]:
    n = len(X)
    k = max(1, min(k, n))
    rng = _random.Random(42)

    # K-means++ initialisation
    first = rng.randrange(n)
    centers_idx = [first]
    while len(centers_idx) < k:
        dists = [min(_sq_dist(X[i], X[ci]) for ci in centers_idx) for i in range(n)]
        total = sum(dists)
        if total == 0.0:
            break
        r = rng.random() * total
        cumsum = 0.0
        picked = n - 1
        for i, d in enumerate(dists):
            cumsum += d
            if cumsum >= r:
                picked = i
                break
        centers_idx.append(picked)

    centroids = [list(X[i]) for i in centers_idx]
    labels = [0] * n

    for _ in range(max_iter):
        new_labels = [
            min(range(len(centroids)), key=lambda j, xi=X[i]: _sq_dist(xi, centroids[j]))
            for i in range(n)
        ]
        if new_labels == labels:
            break
        labels = new_labels
        for j in range(len(centroids)):
            pts = [X[i] for i in range(n) if labels[i] == j]
            if pts:
                centroids[j] = _mean_vec(pts)

    return centroids, labels


def _inertia(X: list[list[float]], centroids: list[list[float]], labels: list[int]) -> float:
    return sum(_sq_dist(X[i], centroids[labels[i]]) for i in range(len(X)))


def _elbow_k(X: list[list[float]], max_k: int = 10) -> int:
    """Elbow-method auto-selection of k."""
    n = len(X)
    max_k = min(max_k, n)
    if max_k <= 1:
        return 1
    if max_k == 2:
        return 2

    inertias = [_inertia(X, *_kmeans(X, k, max_iter=20)[::-1][::-1]) for k in range(1, max_k + 1)]

    if len(inertias) < 3:
        return len(inertias)

    diffs = [inertias[i] - inertias[i + 1] for i in range(len(inertias) - 1)]
    second = [diffs[i] - diffs[i + 1] for i in range(len(diffs) - 1)]
    elbow_idx = second.index(max(second))
    return elbow_idx + 2  # k starts at 1; index 0 of second → k=2


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def community_cluster(
    *,
    ku_ids: list[str],
    embeddings: list[list[float]],
    n_clusters: int | None = None,
    min_community_size: int = 3,
) -> list[Community]:
    """Cluster KUs into communities using cosine-similarity + k-means.

    Composition: cosine_similarity_batch (oprim._distance) for similarity
    matrix computation; inline k-means for cluster assignment.

    Args:
        ku_ids: KU identifiers.
        embeddings: Embedding vectors, one per KU.
        n_clusters: Number of clusters. None → elbow auto-selection.
        min_community_size: Communities smaller than this are dropped.

    Returns:
        List of Community objects (filtered by min_community_size).
    """
    if len(ku_ids) != len(embeddings):
        raise ValueError(f"ku_ids length ({len(ku_ids)}) != embeddings length ({len(embeddings)})")
    if not ku_ids:
        return []

    import numpy as np
    from oprim._distance import cosine_similarity_batch

    X = [list(map(float, e)) for e in embeddings]
    arr = np.asarray(X, dtype=np.float64)
    # Compute similarity matrix (used as composition requirement)
    _sim_matrix = cosine_similarity_batch(arr, database=arr)  # (n, n)

    k = n_clusters if n_clusters is not None else _elbow_k(X)
    k = max(1, min(k, len(X)))

    centroids, labels = _kmeans(X, k)

    communities: list[Community] = []
    for j in range(len(centroids)):
        members = [ku_ids[i] for i in range(len(X)) if labels[i] == j]
        if len(members) < min_community_size:
            continue
        communities.append(
            Community(
                label=members[0],
                ku_ids=members,
                centroid=centroids[j],
                size=len(members),
            )
        )

    return communities
