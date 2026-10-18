"""K-AII-2: capability_gap_analyze — pure-stat KU library gap report.

Composition: query_cluster (K-AII-1, depth-1) + inline statistical aggregation.
No LLM. Every gap fact is reproducible from the input data.
"""

from __future__ import annotations

from oprim._aii_types import GapReport

from oskill._query_cluster import query_cluster


def capability_gap_analyze(
    *,
    grade_distribution: dict,
    failure_stats: dict,
    graph_stats: dict,
    stale_threshold_days: int = 7,
    stale_candidates: list[dict] | None = None,
) -> GapReport:
    """Compute objective KU library capability gaps.

    Args:
        grade_distribution: {domain: {grade: count}}.
        failure_stats: {topic: miss_count} or {topic: {"miss_count": int, ...}}.
        graph_stats: {ku_id: {"degree": int} | int}.
        stale_threshold_days: Minimum days-unverified for a KU to be considered stale.
            0 means every unverified KU is stale regardless of age.
        stale_candidates: [{ku_id, days_unverified, verified}, ...].

    Returns:
        GapReport — no remediation suggestions, only objective gap facts.
    """
    return GapReport(
        high_miss_topics=_compute_high_miss_topics(failure_stats),
        stale_unverified=_compute_stale_unverified(stale_candidates, stale_threshold_days),
        isolated_kus=_compute_isolated_kus(graph_stats),
        grade_imbalance=_compute_grade_imbalance(grade_distribution),
    )


# ---------------------------------------------------------------------------
# Sub-computations
# ---------------------------------------------------------------------------


def _compute_high_miss_topics(failure_stats: dict) -> list[dict]:
    """Cluster miss-topics and sum miss counts per cluster."""
    if not failure_stats:
        return []

    topic_miss: dict[str, int] = {}
    for topic, value in failure_stats.items():
        count = int(value["miss_count"]) if isinstance(value, dict) else int(value)
        if count > 0:
            topic_miss[topic] = count

    if not topic_miss:
        return []

    topics = list(topic_miss.keys())
    cluster_result = query_cluster(texts=topics, min_cluster_size=1)

    result: list[dict] = []
    for cluster in cluster_result.clusters:
        total_miss = sum(topic_miss.get(m, 0) for m in cluster["members"])
        result.append({"topic": cluster["representative"], "miss_count": total_miss})

    result.sort(key=lambda x: x["miss_count"], reverse=True)
    return result


def _compute_stale_unverified(
    stale_candidates: list[dict] | None,
    threshold_days: int,
) -> list[str]:
    """Return ku_ids that are unverified and at or beyond the stale threshold."""
    if not stale_candidates:
        return []

    return [
        str(c["ku_id"])
        for c in stale_candidates
        if not c.get("verified", True) and int(c.get("days_unverified", 0)) >= threshold_days
    ]


def _compute_isolated_kus(graph_stats: dict) -> list[str]:
    """Return ku_ids whose graph degree is 0."""
    isolated: list[str] = []
    for ku_id, stats in graph_stats.items():
        degree = int(stats["degree"]) if isinstance(stats, dict) else int(stats)
        if degree == 0:
            isolated.append(str(ku_id))
    return isolated


def _compute_grade_imbalance(grade_distribution: dict) -> dict:
    """Normalise grade counts to int; pass through structure unchanged."""
    result: dict = {}
    for domain, grades in grade_distribution.items():
        if isinstance(grades, dict):
            result[domain] = {grade: int(count) for grade, count in grades.items()}
        else:
            result[domain] = grades
    return result
