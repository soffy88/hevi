"""Market radar as planning evidence, never canon authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from hevi.obase.creative import CreativeAuthority, ProvenanceRef


class TrendEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: UUID = Field(default_factory=uuid4)
    topic: str
    value: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: ProvenanceRef


class TrendSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    evidence: tuple[TrendEvidence, ...] = ()
    authority: CreativeAuthority = CreativeAuthority.EVIDENCE


@dataclass(frozen=True)
class MarketTrend:
    topic: str
    direction: str
    evidence_ids: tuple[UUID, ...]


class MarketRadar:
    def snapshot(self, *, project_id: UUID, evidence: tuple[TrendEvidence, ...]) -> TrendSnapshot:
        return TrendSnapshot(project_id=project_id, evidence=evidence)

    def summarize(self, snapshot: TrendSnapshot) -> tuple[MarketTrend, ...]:
        by_topic: dict[str, list[TrendEvidence]] = {}
        for evidence in snapshot.evidence:
            by_topic.setdefault(evidence.topic, []).append(evidence)
        return tuple(
            MarketTrend(topic, evidence[0].value, tuple(item.evidence_id for item in evidence))
            for topic, evidence in sorted(by_topic.items())
        )


__all__ = ["MarketRadar", "MarketTrend", "TrendEvidence", "TrendSnapshot"]
