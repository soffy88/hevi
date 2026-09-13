"""Deterministic metadata/temporal retrieval; embeddings are optional."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .models import StrictModel


class RetrievalQuery(StrictModel):
    query_id: str
    raw_intent: str
    subqueries: list[dict[str, Any]] = Field(default_factory=list)


class RetrievalResult(StrictModel):
    asset_id: str
    start_ms: int
    end_ms: int
    score: float
    score_components: dict[str, float]
    reason: str
    evidence_refs: list[str] = Field(default_factory=list)


class VideoTemporalIndex(StrictModel):
    schema_version: int = 1
    entries: list[dict[str, Any]] = Field(default_factory=list)

    @classmethod
    def from_analysis(cls, analysis: Any) -> VideoTemporalIndex:
        return cls(entries=[{
            "asset_id": shot.asset_id,
            "start_ms": shot.start_ms,
            "end_ms": shot.end_ms,
            "semantic_text": shot.semantic.description,
            "structured_tags": [shot.semantic.category.value, shot.semantic.camera_motion.value],
            "shot_refs": [shot.shot_id],
            "event_refs": [],
        } for shot in analysis.shots])

    def retrieve(self, query: RetrievalQuery, limit: int = 5) -> list[RetrievalResult]:
        words = set(query.raw_intent.lower().split())
        rows: list[RetrievalResult] = []
        for entry in self.entries:
            text = f"{entry['semantic_text']} {' '.join(entry['structured_tags'])}".lower()
            overlap = len(words & set(text.split()))
            score = overlap / max(1, len(words))
            rows.append(RetrievalResult(
                asset_id=entry["asset_id"], start_ms=entry["start_ms"], end_ms=entry["end_ms"],
                score=score, score_components={"metadata_overlap": score},
                reason="indexed metadata match" if score else "indexed temporal candidate",
                evidence_refs=entry["shot_refs"],
            ))
        return sorted(rows, key=lambda row: (-row.score, row.start_ms))[:limit]
