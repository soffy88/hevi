"""Strict contracts for the persistent Case Learning intelligence layer."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from .models import StrictModel


class IntelligenceStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class PatternLifecycle(StrEnum):
    CANDIDATE = "candidate"
    OBSERVED = "observed"
    QUALIFIED = "qualified"
    PROMOTED = "promoted"
    DEPRECATED = "deprecated"


class EvidenceType(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    COUNTER_EXAMPLE = "counter_example"


class BenchmarkPlan(StrictModel):
    id: str
    case_id: str
    analysis_revision: str
    generation_mode: str
    compiled_semantic_intent: str
    shot_structure: list[dict[str, Any]] = Field(default_factory=list)
    reference_bindings: list[dict[str, Any]] = Field(default_factory=list)
    duration_ms: int | None = None
    aspect_ratio: str | None = None
    acceptance_dimensions: list[str] = Field(default_factory=list)
    plan_hash: str


class BenchmarkEntry(StrictModel):
    reproduction_id: str
    provider_id: str
    model_id: str
    verdict_id: str | None = None
    dimension_comparison: dict[str, Any] = Field(default_factory=dict)
    cost: float | None = None
    latency_ms: float | None = None


class CaseBenchmark(StrictModel):
    id: str
    case_id: str
    benchmark_plan_id: str
    status: IntelligenceStatus = IntelligenceStatus.PENDING
    provider_count: int = 0
    reproduction_count: int = 0
    entries: list[BenchmarkEntry] = Field(default_factory=list)
    failure_code: str | None = None


class PatternClusterCandidate(StrictModel):
    id: str
    pattern_ids: list[str]
    evidence_ids: list[str]
    algorithm: str
    algorithm_version: str
    confidence: float = Field(ge=0, le=1)
    suggestion_only: bool = True


class TemplateQualificationRun(StrictModel):
    id: str
    template_id: str
    status: IntelligenceStatus = IntelligenceStatus.PENDING
    case_ids: list[str] = Field(default_factory=list)
    reproduction_ids: list[str] = Field(default_factory=list)
    baseline_revision: str | None = None
    dimension_deltas: dict[str, Any] = Field(default_factory=dict)


class ProductionLearningEvent(StrictModel):
    id: str
    production_id: str
    shot_id: str
    provider_id: str
    model_id: str
    model_version: str | None = None
    template_id: str | None = None
    template_revision: int | None = None
    pattern_ids: list[str] = Field(default_factory=list)
    prompt_hash: str | None = None
    generation_mode: str = "unknown"
    generation_cost: float | None = None
    latency_ms: float | None = None
    retake_count: int = 0
    initial_verdict_id: str | None = None
    final_verdict_id: str | None = None
    final_status: str
    idempotency_key: str


class RetakeOutcome(StrEnum):
    IMPROVED = "improved"
    UNCHANGED = "unchanged"
    REGRESSED = "regressed"
    FAILED = "failed"


class RetakeLearningRecord(StrictModel):
    id: str
    production_id: str
    shot_id: str
    failure_reason_codes: list[str] = Field(default_factory=list)
    retake_level: str
    retake_strategy: str
    changed_prompt: bool = False
    changed_provider: bool = False
    changed_reference: bool = False
    changed_duration: bool = False
    changed_camera: bool = False
    before_verdict_id: str | None = None
    after_verdict_id: str | None = None
    cost_delta: float | None = None
    latency_delta: float | None = None
    outcome: RetakeOutcome
    multi_variable_retake: bool = False


__all__ = [
    "BenchmarkEntry", "BenchmarkPlan", "CaseBenchmark", "EvidenceType",
    "IntelligenceStatus", "PatternClusterCandidate", "PatternLifecycle",
    "ProductionLearningEvent", "RetakeLearningRecord", "RetakeOutcome",
    "TemplateQualificationRun",
]
