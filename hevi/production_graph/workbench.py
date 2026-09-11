"""Persisted P1 Director Workbench records.

These records are product-control projections around the immutable P0 graph.
They never replace ProductionRevision, ExecutionPlan, or Artifact authority.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(UTC)


class CandidateState(StrEnum):
    CANDIDATE = "CANDIDATE"
    SELECTED = "SELECTED"
    LOCKED = "LOCKED"
    REJECTED = "REJECTED"
    ARCHIVED = "ARCHIVED"


class CandidateRecord(BaseModel):
    id: str
    project_id: str
    shot_id: str
    execution_attempt_id: str
    execution_plan_id: str
    artifact_id: str | None = None
    state: CandidateState = CandidateState.CANDIDATE
    revision_id: str
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class CreativeMemoryKind(StrEnum):
    ACCEPTED_PREFERENCE = "accepted_preference"
    REJECTED_DIRECTION = "rejected_direction"
    LOCKED_DECISION = "locked_decision"
    PROJECT_SUMMARY = "project_summary"
    UNRESOLVED_CONCERN = "unresolved_concern"


class CreativeMemoryRecord(BaseModel):
    id: str
    project_id: str
    scope: str
    scope_id: str | None = None
    kind: CreativeMemoryKind
    content: str
    source_session_id: str | None = None
    revision_id: str
    created_at: datetime = Field(default_factory=_now)
    active: bool = True


class VersionRecord(BaseModel):
    id: str
    project_id: str
    registry_type: str  # prompt | skill
    name: str
    version: str
    content: str
    active: bool = False
    created_at: datetime = Field(default_factory=_now)


class TemplatePolicy(BaseModel):
    template_id: str
    name: str
    production_mode: str
    aspect_ratio: str
    target_duration: float | None = None
    visual_style: str = ""
    shot_strategy: str = ""
    audio_strategy: str = ""
    qa_policy: str = "standard"


class DependencyStatus(StrEnum):
    VALID = "VALID"
    STALE = "STALE"
    NEEDS_REBUILD = "NEEDS_REBUILD"


class DependencyRecord(BaseModel):
    id: str
    project_id: str
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    status: DependencyStatus = DependencyStatus.VALID
    reason: str = ""
    revision_id: str


def workbench_record_payload(record: BaseModel) -> dict[str, Any]:
    return record.model_dump(mode="json")


__all__ = [
    "CandidateRecord",
    "CandidateState",
    "CreativeMemoryKind",
    "CreativeMemoryRecord",
    "DependencyRecord",
    "DependencyStatus",
    "TemplatePolicy",
    "VersionRecord",
    "workbench_record_payload",
]
