"""Spectral asset clustering via MST, PMFG, and spectral Laplacian methods.

References
----------
Mantegna, R.N. (1999). Hierarchical structure in financial markets.
    European Physical Journal B, 11(1), 193-197.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import minimum_spanning_tree
from sklearn.cluster import KMeans

try:
    from oprim.spectral.eigengap import spectral_eigengap_detect
except ImportError:
    spectral_eigengap_detect = None  # type: ignore[assignment]

from oskill.spectral.laplacian import graph_laplacian_compute


def _compute_distance(
    correlation_matrix: np.ndarray,
    distance_transform: Literal["mantegna", "absolute"],
) -> np.ndarray:
    rho = np.clip(correlation_matrix, -1.0, 1.0)
    if distance_transform == "mantegna":
        return np.sqrt(np.clip(2.0 * (1.0 - rho), 0.0, None))
    else:  # absolute
        return 1.0 - np.abs(rho)


def _compute_modularity(adjacency: np.ndarray, labels: np.ndarray) -> float:
    """Compute Newman-Girvan modularity."""
    m = adjacency.sum()
    if m == 0:
        return 0.0
    k = adjacency.sum(axis=1)
    N = len(labels)
    Q = 0.0
    for i in range(N):
        for j in range(N):
            if labels[i] == labels[j]:
                Q += adjacency[i, j] - k[i] * k[j] / (2.0 * m)
    return float(Q / (2.0 * m))


def spectral_asset_clustering(
    correlation_matrix: np.ndarray,
    *,
    method: Literal["mst", "pmfg", "spectral_laplacian"] = "spectral_laplacian",
    n_clusters: int | None = None,
    distance_transform: Literal["mantegna", "absolute"] = "mantegna",
    clustering_algorithm: Literal["kmeans", "leiden"] = "leiden",
) -> dict[str, Any]:
    """Cluster assets using spectral graph methods.

    Parameters
    ----------
    correlation_matrix : np.ndarray
        Square symmetric correlation matrix of shape (N, N).
    method : {"mst", "pmfg", "spectral_laplacian"}
        Graph construction method.
    n_clusters : int or None
        Number of clusters. If None, inferred via eigengap.
    distance_transform : {"mantegna", "absolute"}
        Distance metric derived from correlations.
    clustering_algorithm : {"kmeans", "leiden"}
        Clustering algorithm (leiden falls back to kmeans).

    Returns
    -------
    dict with keys:
        ``cluster_labels`` — integer label per asset.
        ``graph_edges`` — list of (i, j, weight) edge tuples.
        ``modularity`` — modularity score Q.
        ``n_clusters_inferred`` — number of clusters used.
    """
    corr = np.asarray(correlation_matrix, dtype=float)
    N = corr.shape[0]
    if corr.ndim != 2 or corr.shape[0] != corr.shape[1]:
        raise ValueError("correlation_matrix must be square 2-D")

    dist = _compute_distance(corr, distance_transform)
    np.fill_diagonal(dist, 0.0)

    # Determine k
    k_default = 5
    k: int

    if method == "mst":
        sparse_dist = csr_matrix(dist)
        mst = minimum_spanning_tree(sparse_dist)
        mst_dense = mst.toarray()
        # Symmetrize
        adjacency = mst_dense + mst_dense.T

        # Infer k
        if n_clusters is not None:
            k = int(n_clusters)
        else:
            k = min(k_default, N)

        # Cluster by removing k-1 longest edges
        all_mst_edges = [
            (adjacency[i, j], i, j)
            for i in range(N)
            for j in range(i + 1, N)
            if adjacency[i, j] > 0
        ]
        edges_sorted = sorted(all_mst_edges, reverse=True)
        # Build clusters via BFS
        graph_adj = {i: [] for i in range(N)}
        for w, i, j in edges_sorted[k - 1 :]:
            graph_adj[i].append(j)
            graph_adj[j].append(i)
        labels = np.full(N, -1, dtype=int)
        cluster_id = 0
        for start in range(N):
            if labels[start] == -1:
                queue = [start]
                while queue:
                    node = queue.pop()
                    if labels[node] == -1:
                        labels[node] = cluster_id
                        queue.extend(graph_adj[node])
                cluster_id += 1

        edges_list = [(i, j, float(adjacency[i, j])) for _, i, j in edges_sorted[k - 1 :]]
        graph_edges = edges_list

    elif method == "pmfg":
        # Simplified: take 3*(N-2) edges with smallest distance (planar bound)
        n_edges = max(1, 3 * (N - 2))
        triu_idx = np.triu_indices(N, k=1)
        distances_flat = dist[triu_idx]
        sorted_idx = np.argsort(distances_flat)[:n_edges]
        adjacency = np.zeros((N, N))
        for idx in sorted_idx:
            i, j = triu_idx[0][idx], triu_idx[1][idx]
            w = 1.0 - dist[i, j]  # affinity
            adjacency[i, j] = w
            adjacency[j, i] = w

        if n_clusters is not None:
            k = int(n_clusters)
        else:
            k = min(k_default, N)

        km = KMeans(n_clusters=k, random_state=42, n_init="auto")
        labels = km.fit_predict(adjacency)
        graph_edges = []
        for idx in sorted_idx:
            ii, jj = int(triu_idx[0][idx]), int(triu_idx[1][idx])
            graph_edges.append((ii, jj, float(adjacency[ii, jj])))

    else:  # spectral_laplacian
        # Affinity: max(0, correlation)
        affinity = np.maximum(0.0, corr)
        np.fill_diagonal(affinity, 0.0)

        # Infer k
        if n_clusters is not None:
            k = int(n_clusters)
        elif spectral_eigengap_detect is not None:
            lap_result = graph_laplacian_compute(
                affinity, normalization="symmetric", n_eigenvalues=min(20, N)
            )
            eigs = lap_result["eigenvalues"]
            eg_result = spectral_eigengap_detect(eigs, method="largest_gap", max_k=min(10, N - 1))
            k = int(eg_result.get("n_components", k_default))
            k = max(2, min(k, N - 1))
        else:
            k = min(k_default, N)

        lap_result = graph_laplacian_compute(
            affinity, normalization="symmetric", n_eigenvalues=min(k + 2, N)
        )
        eigvecs = lap_result["eigenvectors"][:, :k]  # (N, k)

        # Normalize rows
        norms = np.linalg.norm(eigvecs, axis=1, keepdims=True)
        norms = np.where(norms < 1e-12, 1.0, norms)
        eigvecs_norm = eigvecs / norms

        km = KMeans(n_clusters=k, random_state=42, n_init="auto")
        labels = km.fit_predict(eigvecs_norm)

        triu_idx = np.triu_indices(N, k=1)
        graph_edges = []
        for idx in range(len(triu_idx[0])):
            ii, jj = int(triu_idx[0][idx]), int(triu_idx[1][idx])
            if affinity[ii, jj] > 0:
                graph_edges.append((ii, jj, float(affinity[ii, jj])))
        adjacency = affinity

    modularity = _compute_modularity(adjacency, labels)

    return {
        "cluster_labels": labels,
        "graph_edges": graph_edges,
        "modularity": float(modularity),
        "n_clusters_inferred": int(k),
    }
