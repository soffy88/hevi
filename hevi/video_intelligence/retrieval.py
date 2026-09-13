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


def temporal_iou(
    observed_start_ms: int, observed_end_ms: int, expected_start_ms: int, expected_end_ms: int
) -> float:
    intersection = max(0, min(observed_end_ms, expected_end_ms) - max(observed_start_ms, expected_start_ms))
    union = max(observed_end_ms, expected_end_ms) - min(observed_start_ms, expected_start_ms)
    return intersection / union if union else 0.0


def evaluate_retrieval(
    ranked: list[list[RetrievalResult]],
    ground_truth: list[dict[str, Any]],
    *,
    iou_threshold: float = 0.5,
) -> dict[str, float | int]:
    if len(ranked) != len(ground_truth):
        raise ValueError("retrieval result and ground truth counts differ")
    hits_at_1 = hits_at_5 = 0
    reciprocal_sum = 0.0
    iou_sum = 0.0
    for results, expected in zip(ranked, ground_truth, strict=True):
        matches = [
            temporal_iou(row.start_ms, row.end_ms, expected["start_ms"], expected["end_ms"])
            for row in results
            if row.asset_id == expected["asset_id"]
        ]
        hit_ranks = [index + 1 for index, value in enumerate(matches) if value >= iou_threshold]
        if hit_ranks:
            rank = hit_ranks[0]
            hits_at_1 += rank == 1
            hits_at_5 += rank <= 5
            reciprocal_sum += 1 / rank
            iou_sum += max(matches)
    count = len(ground_truth)
    return {
        "recall_at_1": hits_at_1 / count if count else 0.0,
        "recall_at_5": hits_at_5 / count if count else 0.0,
        "mrr": reciprocal_sum / count if count else 0.0,
        "temporal_iou": iou_sum / count if count else 0.0,
        "query_count": count,
        "iou_threshold": iou_threshold,
    }


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
