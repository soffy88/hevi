"""Canonical creative provenance helpers layered on the existing artifacts."""

from __future__ import annotations

from collections.abc import Iterable
from itertools import pairwise
from typing import Any

from hevi.production_graph.domain import ProvenanceLink


def provenance_link(
    *,
    project_id: str,
    source_type: str,
    source_id: str,
    target_type: str,
    target_id: str,
    relation: str,
    metadata: dict[str, Any] | None = None,
) -> ProvenanceLink:
    return ProvenanceLink(
        project_id=project_id,
        source_type=source_type,
        source_id=source_id,
        target_type=target_type,
        target_id=target_id,
        relation=relation,
        metadata=dict(metadata or {}),
    )


def provenance_chain(project_id: str, nodes: Iterable[tuple[str, str]]) -> list[ProvenanceLink]:
    """Create a linear source-to-artifact chain for deterministic fixtures."""

    items = list(nodes)
    return [
        provenance_link(
            project_id=project_id,
            source_type=source_type,
            source_id=source_id,
            target_type=target_type,
            target_id=target_id,
            relation="DERIVES",
        )
        for (source_type, source_id), (target_type, target_id) in pairwise(items)
    ]


__all__ = ["provenance_chain", "provenance_link"]
