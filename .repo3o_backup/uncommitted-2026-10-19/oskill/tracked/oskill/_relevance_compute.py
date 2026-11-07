"""K-G3: relevance_compute — composite KU relevance scoring.

Composition (docstring):
  - direct_link_score   (oprim P-G4)
  - source_overlap_score (oprim P-G5)
  - adamic_adar_score   (oprim P-G6)
  - type_affinity_score  (oprim P-G7)

Pure computation, no LLM. Weights injectable.
"""

from __future__ import annotations

from oprim._adamic_adar_score import adamic_adar_score
from oprim._direct_link_score import direct_link_score
from oprim._source_overlap_score import source_overlap_score
from oprim._type_affinity_score import type_affinity_score

_DEFAULT_WEIGHTS: dict[str, float] = {
    "direct": 1.0,
    "source": 1.0,
    "adamic": 1.0,
    "type": 1.0,
}


def relevance_compute(
    *,
    ku_id_a: str,
    ku_id_b: str,
    edges: list[dict],
    sources_a: list[str],
    sources_b: list[str],
    neighbors_a: list[str],
    neighbors_b: list[str],
    neighbor_degree: dict[str, int],
    type_a: str,
    type_b: str,
    weights: dict[str, float] | None = None,
) -> float:
    """Compute composite relevance between two KUs.

    Composition: direct_link_score + source_overlap_score +
    adamic_adar_score + type_affinity_score.
    Default weights: {direct: 1.0, source: 1.0, adamic: 1.0, type: 1.0}.
    Custom weights injectable and merged with defaults.
    """
    w = dict(_DEFAULT_WEIGHTS)
    if weights:
        w.update(weights)

    direct = direct_link_score(ku_id_a=ku_id_a, ku_id_b=ku_id_b, edges=edges)
    source = source_overlap_score(sources_a=sources_a, sources_b=sources_b)
    adamic = adamic_adar_score(
        neighbors_a=neighbors_a,
        neighbors_b=neighbors_b,
        neighbor_degree=neighbor_degree,
    )
    type_ = type_affinity_score(type_a=type_a, type_b=type_b)

    return w["direct"] * direct + w["source"] * source + w["adamic"] * adamic + w["type"] * type_
