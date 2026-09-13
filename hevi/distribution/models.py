from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DistributionPlatform(StrEnum):
    DOUYIN = "douyin"
    KUAISHOU = "kuaishou"
    BILIBILI = "bilibili"
    XIAOHONGSHU = "xiaohongshu"
    WECHAT_CHANNELS = "wechat_channels"
    TOUTIAO = "toutiao"
    BAIJIAHAO = "baijiahao"
    FANQIE_VIDEO = "fanqie_video"


class DistributionJobState(StrEnum):
    CREATED = "CREATED"
    VALIDATING = "VALIDATING"
    QUEUED = "QUEUED"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    SCHEDULED = "SCHEDULED"
    DRAFTED = "DRAFTED"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"
    RETRYABLE_FAILED = "RETRYABLE_FAILED"
    TERMINAL_FAILED = "TERMINAL_FAILED"


class DistributionBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DistributionAccount(DistributionBase):
    account_ref: str
    platform: DistributionPlatform
    display_name: str | None = None
    logged_in: bool
    capabilities: list[str] = Field(default_factory=list)
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class DistributionTarget(DistributionBase):
    platform: DistributionPlatform
    account_ref: str
    title: str = Field(min_length=1)
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    scheduled_at: datetime | None = None
    draft: bool = False


class DistributionArtifact(DistributionBase):
    artifact_id: str
    sha256: str
    uri: str
    media_type: str = "video/mp4"
    byte_size: int | None = None
    ffprobe: dict[str, Any] = Field(default_factory=dict)


class DistributionProvenance(DistributionBase):
    source_artifact_id: str
    source_artifact_sha256: str
    provider: str
    platform: DistributionPlatform
    account_ref: str
    provider_request: dict[str, Any] = Field(default_factory=dict)
    provider_job_ref: str | None = None
    provider_result: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class DistributionJob(DistributionBase):
    distribution_job_id: str
    source_artifact_id: str
    source_artifact_sha256: str
    provider: str
    platform: DistributionPlatform
    account_ref: str
    title: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    scheduled_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    attempt: int = 0
    idempotency_key: str
    provider_job_ref: str | None = None
    state: DistributionJobState = DistributionJobState.CREATED
    failure_class: str | None = None
    provenance: DistributionProvenance | None = None


class DistributionResult(DistributionBase):
    job: DistributionJob
    artifact: DistributionArtifact | None = None
    provider_status: str
    success: bool
    failure_class: str | None = None
    retry_evidence: dict[str, Any] = Field(default_factory=dict)
    duplicate_side_effects: int = 0
    message: str = ""

