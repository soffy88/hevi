"""Canonical VideoCase contracts.

Cases are evidence records, not a second production or asset system.  Media
references point at HEVI's existing asset authority; this module owns only
case-learning metadata and its provenance boundary.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import Field, field_validator

from .models import StrictModel


class ProvenanceStatus(StrEnum):
    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    UNVERIFIED = "unverified"


class PromptOrigin(StrEnum):
    AUTHOR_PROVIDED = "author_provided"
    PLATFORM_EXTRACTED = "platform_extracted"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


class RightsStatus(StrEnum):
    UNKNOWN = "unknown"
    REFERENCE_ONLY = "reference_only"
    PERMITTED = "permitted"
    OWNED = "owned"


class CaseAnalysisStatus(StrEnum):
    NOT_STARTED = "not_started"
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


class DuplicateOutcome(StrEnum):
    NEW = "new"
    EXACT_DUPLICATE = "exact_duplicate"
    LIKELY_DUPLICATE = "likely_duplicate"


class CaseIngestInput(StrictModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    source_url: str | None = None
    source_platform: str | None = None
    source_author: str | None = None
    local_video_path: str | None = None
    uploaded_asset_id: str | None = None
    existing_asset_id: str | None = None
    original_prompt: str | None = None
    prompt_origin: PromptOrigin = PromptOrigin.UNKNOWN
    reference_assets: list[dict[str, Any]] = Field(default_factory=list)
    declared_model: str | None = None
    declared_model_version: str | None = None
    rights_status: RightsStatus = RightsStatus.UNKNOWN
    rights_metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    idempotency_key: str | None = Field(default=None, max_length=255)

    @field_validator("source_url")
    @classmethod
    def valid_source_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source_url must be an absolute http(s) URL")
        return value

    @field_validator("prompt_origin")
    @classmethod
    def prompt_origin_requires_prompt(cls, value: PromptOrigin, info: Any) -> PromptOrigin:
        prompt = info.data.get("original_prompt")
        if value in {PromptOrigin.AUTHOR_PROVIDED, PromptOrigin.PLATFORM_EXTRACTED, PromptOrigin.INFERRED} and not prompt:
            raise ValueError("original_prompt is required when prompt_origin is not unknown")
        return value


class AssetRef(StrictModel):
    asset_id: str
    role: str
    target: str | None = None
    strength: float | None = Field(default=None, ge=0, le=1)
    provenance_ref: str | None = None


class ProvenanceRecord(StrictModel):
    source_type: str
    source_uri: str | None = None
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    evidence_hash: str
    extraction_method: str
    confidence: float | None = Field(default=None, ge=0, le=1)


class CaseShot(StrictModel):
    shot_index: int = Field(ge=1)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    framing: str | None = None
    camera_angle: str | None = None
    camera_motion: str | None = None
    subject_state_start: str | None = None
    subject_action: str | None = None
    subject_state_end: str | None = None
    environment_state: str | None = None
    audio_events: list[dict[str, Any]] = Field(default_factory=list)
    transition_in: str | None = None
    transition_out: str | None = None

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


class VideoCase(StrictModel):
    id: str
    user_id: str
    title: str
    description: str | None = None
    source_url: str | None = None
    source_platform: str | None = None
    source_author: str | None = None
    provenance_status: ProvenanceStatus = ProvenanceStatus.UNVERIFIED
    provenance: list[ProvenanceRecord] = Field(default_factory=list)
    original_video_asset_id: str | None = None
    thumbnail_asset_id: str | None = None
    original_prompt: str | None = None
    prompt_origin: PromptOrigin = PromptOrigin.UNKNOWN
    reference_assets: list[AssetRef] = Field(default_factory=list)
    duration_ms: int | None = Field(default=None, ge=0)
    aspect_ratio: str | None = None
    fps: float | None = Field(default=None, gt=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    declared_model: str | None = None
    declared_model_version: str | None = None
    rights_status: RightsStatus = RightsStatus.UNKNOWN
    rights_metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    analysis_status: CaseAnalysisStatus = CaseAnalysisStatus.NOT_STARTED
    duplicate_outcome: DuplicateOutcome = DuplicateOutcome.NEW
    exact_asset_sha256: str | None = None
    source_fingerprint: str | None = None
    shots: list[CaseShot] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def media_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_source_fingerprint(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"\s+", "", value).lower()[:512]


__all__ = [
    "AssetRef", "CaseAnalysisStatus", "CaseIngestInput", "CaseShot",
    "DuplicateOutcome", "PromptOrigin", "ProvenanceRecord", "ProvenanceStatus",
    "RightsStatus", "VideoCase", "media_sha256", "normalize_source_fingerprint",
]
