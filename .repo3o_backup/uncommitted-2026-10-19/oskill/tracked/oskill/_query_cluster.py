"""K-AII-1: query_cluster — two-stage deterministic text clustering.

Stage 1: keyword_merge (P-AII-2) coarse grouping.
Stage 2: cosine_similarity_batch (♻️ oprim._distance) embedding refinement.
No LLM; same input → same output.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
from oprim._aii_types import ClusterResult
from oprim._distance import cosine_similarity_batch
from oprim._keyword_merge import keyword_merge


def query_cluster(
    *,
    texts: list[str],
    embeddings: list[list[float]] | None = None,
    similarity_threshold: float = 0.6,
    min_cluster_size: int = 2,
) -> ClusterResult:
    """Two-stage deterministic text clustering.

    Stage 1 (always): keyword_merge coarse grouping by token overlap.
    Stage 2 (when embeddings provided): cosine_similarity_batch refinement
        that merges clusters whose representatives exceed similarity_threshold.

    min_cluster_size filters small clusters from the output; clusters already
    at size == 1 from single-item input are never filtered.

    Args:
        texts: Strings to cluster.
        embeddings: Pre-computed float vectors aligned 1:1 with texts.
                    None → keyword stage only.
        similarity_threshold: Minimum cosine similarity to merge clusters.
        min_cluster_size: Minimum member count for a cluster to appear in output.

    Returns:
        ClusterResult.clusters list of {representative, members, size}.
    """
    if not texts:
        return ClusterResult(clusters=[])

    if len(texts) == 1:
        return ClusterResult(
            clusters=[{"representative": texts[0], "members": [texts[0]], "size": 1}]
        )

    # Stage 1: keyword coarse-grouping
    kw_groups = keyword_merge(texts)
    clusters_raw: list[dict] = [
        {"representative": rep, "members": members, "size": len(members)}
        for rep, members in kw_groups.items()
    ]

    # Stage 2: embedding refinement
    if embeddings is not None:
        clusters_raw = _refine_with_embeddings(
            texts, embeddings, clusters_raw, similarity_threshold
        )

    # Apply min_cluster_size filter
    filtered = [c for c in clusters_raw if c["size"] >= min_cluster_size]
    # Protect against over-filtering: if everything was filtered, keep originals
    return ClusterResult(clusters=filtered if filtered else clusters_raw)


def _refine_with_embeddings(
    texts: list[str],
    embeddings: list[list[float]],
    initial_clusters: list[dict],
    threshold: float,
) -> list[dict]:
    """Merge keyword clusters whose representative embeddings exceed threshold."""
    n = len(initial_clusters)
    if n <= 1:
        return initial_clusters

    emb_array = np.array(embeddings, dtype=np.float64)
    text_to_idx: dict[str, int] = {t: i for i, t in enumerate(texts)}

    # Representative embedding for each cluster (first text in texts order if ambiguous)
    rep_indices: list[int] = []
    for c in initial_clusters:
        rep_indices.append(text_to_idx[c["representative"]])
    rep_emb = emb_array[rep_indices]

    # Union-Find on cluster indices
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            if ra < rb:
                parent[rb] = ra
            else:
                parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            sim_raw = cosine_similarity_batch(rep_emb[i], database=rep_emb[j : j + 1])
            sim_val = float(np.asarray(sim_raw).ravel()[0])
            if sim_val >= threshold:
                union(i, j)

    groups: dict[int, list[int]] = defaultdict(list)
    for idx in range(n):
        groups[find(idx)].append(idx)

    merged: list[dict] = []
    for root, cluster_indices in sorted(groups.items()):
        all_members: list[str] = []
        for ci in cluster_indices:
            all_members.extend(initial_clusters[ci]["members"])
        merged.append(
            {
                "representative": initial_clusters[root]["representative"],
                "members": all_members,
                "size": len(all_members),
            }
        )

    return merged
