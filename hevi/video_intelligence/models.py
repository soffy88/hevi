"""Versioned, serializable Video Intelligence domain contracts.

Machine evidence is deliberately separate from semantic annotations.  A
semantic adapter may propose labels, but it cannot mutate timestamps or
measurements produced by ffprobe/ffmpeg.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

VIDEO_INTELLIGENCE_CONTRACT_VERSION = 1


def _now() -> datetime:
    return datetime.now(UTC)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class SourceType(StrEnum):
    GENERATED = "GENERATED"
    UPLOADED = "UPLOADED"
    REFERENCE = "REFERENCE"
    LIBRARY = "LIBRARY"
    PUBLIC_LICENSED = "PUBLIC_LICENSED"


class MotionClass(StrEnum):
    STATIC = "STATIC"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ShotSize(StrEnum):
    EXTREME_WIDE = "EXTREME_WIDE"
    WIDE = "WIDE"
    MEDIUM_WIDE = "MEDIUM_WIDE"
    MEDIUM = "MEDIUM"
    MEDIUM_CLOSE = "MEDIUM_CLOSE"
    CLOSE = "CLOSE"
    EXTREME_CLOSE = "EXTREME_CLOSE"
    INSERT = "INSERT"
    UNKNOWN = "UNKNOWN"


class ShotCategory(StrEnum):
    ESTABLISHING = "ESTABLISHING"
    ACTION = "ACTION"
    DIALOGUE = "DIALOGUE"
    REACTION = "REACTION"
    DETAIL = "DETAIL"
    PRODUCT = "PRODUCT"
    TEXT_CARD = "TEXT_CARD"
    BROLL = "BROLL"
    ENVIRONMENT = "ENVIRONMENT"
    POV = "POV"
    SCREEN = "SCREEN"
    TRANSITION = "TRANSITION"
    OTHER = "OTHER"


class CameraMotion(StrEnum):
    LOCKED = "LOCKED"
    PAN = "PAN"
    TILT = "TILT"
    PUSH = "PUSH"
    PULL = "PULL"
    TRUCK = "TRUCK"
    DOLLY = "DOLLY"
    ORBIT = "ORBIT"
    TRACK = "TRACK"
    HANDHELD = "HANDHELD"
    ZOOM = "ZOOM"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class RhythmRole(StrEnum):
    HOOK = "HOOK"
    SETUP = "SETUP"
    BUILD = "BUILD"
    EMPHASIS = "EMPHASIS"
    TURN = "TURN"
    PAYOFF = "PAYOFF"
    BREATH = "BREATH"
    CLOSE = "CLOSE"
    OTHER = "OTHER"


class GateStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"
    NOT_EVALUABLE = "NOT_EVALUABLE"


class VideoAsset(StrictModel):
    schema_version: int = 1
    asset_id: str
    uri: str
    local_path: str
    sha256: str
    duration_s: float
    width: int
    height: int
    fps: float | None = None
    codec: str | None = None
    audio_codec: str | None = None
    created_at: datetime = Field(default_factory=_now)
    source_type: SourceType = SourceType.GENERATED
    license_ref: str | None = None
    provenance_ref: str | None = None


class VideoProbe(StrictModel):
    schema_version: int = 1
    asset_id: str | None = None
    path: str
    duration_ms: int
    fps_num: int | None = None
    fps_den: int | None = None
    frame_count: int | None = None
    width: int | None = None
    height: int | None = None
    pixel_format: str | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    audio_sample_rate: int | None = None
    audio_channels: int | None = None
    bitrate: int | None = None
    container: str | None = None
    has_video: bool = False
    has_audio: bool = False


class ShotBoundaryEvidence(StrictModel):
    timestamp_ms: int
    method: str
    score: float | None = None
    source: str
    manual_boundary_evidence: str | None = None


class MotionEvidence(StrictModel):
    median_frame_delta: float
    mean_frame_delta: float
    p90_frame_delta: float
    motion_class: MotionClass
    sample_count: int
    method: str = "CPU_GRAYSCALE_FRAME_DELTA"


class ShotSemantic(StrictModel):
    size: ShotSize = ShotSize.UNKNOWN
    category: ShotCategory = ShotCategory.OTHER
    camera_motion: CameraMotion = CameraMotion.UNKNOWN
    description: str = ""
    subjects: list[str] = Field(default_factory=list)
    onscreen_text: list[str] = Field(default_factory=list)
    dialogue: bool | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class ShotRhythm(StrictModel):
    role: RhythmRole
    reason: str
    confidence: float | None = Field(default=None, ge=0, le=1)


class ShotObservation(StrictModel):
    schema_version: int = 1
    shot_id: str
    asset_id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    duration_ms: int = Field(gt=0)
    boundary_evidence: list[ShotBoundaryEvidence] = Field(default_factory=list)
    motion_evidence: MotionEvidence | None = None
    semantic: ShotSemantic = Field(default_factory=ShotSemantic)
    rhythm: ShotRhythm | None = None
    frame_refs: list[str] = Field(default_factory=list)
    transcript_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_duration(self) -> ShotObservation:
        if self.end_ms - self.start_ms != self.duration_ms:
            raise ValueError("duration_ms must equal end_ms - start_ms")
        return self


class VideoQualityFinding(StrictModel):
    finding_id: str
    code: str
    status: GateStatus
    severity: str
    message: str
    evidence_refs: list[str] = Field(default_factory=list)
    shot_refs: list[str] = Field(default_factory=list)


class VideoQualityReport(StrictModel):
    schema_version: int = 1
    status: GateStatus
    findings: list[VideoQualityFinding] = Field(default_factory=list)
    checked: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)


class ReelStatistics(StrictModel):
    shot_count: int
    average_shot_duration_ms: float
    median_shot_duration_ms: float
    cuts_per_minute: float
    shot_size_distribution: dict[str, int] = Field(default_factory=dict)
    category_distribution: dict[str, int] = Field(default_factory=dict)
    camera_motion_distribution: dict[str, int] = Field(default_factory=dict)
    rhythm_distribution: dict[str, int] = Field(default_factory=dict)
    motion_distribution: dict[str, int] = Field(default_factory=dict)


class VideoAnalysisProvenance(StrictModel):
    schema_version: int = 1
    source_asset_id: str
    source_sha256: str
    probe_version: str
    boundary_detector_version: str
    motion_analyzer_version: str
    semantic_provider: str | None = None
    semantic_model: str | None = None
    analysis_contract_version: int = VIDEO_INTELLIGENCE_CONTRACT_VERSION
    created_at: datetime = Field(default_factory=_now)
    transcript_source: str | None = None
    manual_adjustments: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class ReelAnalysis(StrictModel):
    schema_version: int = 1
    analysis_id: str
    video_asset: VideoAsset
    video_probe: VideoProbe
    shots: list[ShotObservation]
    statistics: ReelStatistics
    quality_report: VideoQualityReport
    provenance: VideoAnalysisProvenance


class ReferenceProfile(StrictModel):
    schema_version: int = 1
    profile_id: str
    source_analysis_id: str
    shot_duration_profile: dict[str, float]
    cut_frequency: float
    shot_size_profile: dict[str, float]
    camera_profile: dict[str, float]
    rhythm_profile: dict[str, float]
    transition_profile: dict[str, float] = Field(default_factory=dict)
    motion_profile: dict[str, float] = Field(default_factory=dict)
    semantic_sequence: list[str] = Field(default_factory=list)
    visual_pattern_summary: str = ""
    provenance_ref: str


class IntentProfile(StrictModel):
    schema_version: int = 1
    intent_id: str
    narrative_goal: str = ""
    scene_goals: list[str] = Field(default_factory=list)
    required_beats: list[str] = Field(default_factory=list)
    expected_shot_count_range: tuple[int, int] | None = None
    expected_pacing: str | None = None
    required_entities: list[str] = Field(default_factory=list)
    visual_intents: list[str] = Field(default_factory=list)
    required_text: list[str] = Field(default_factory=list)
    audio_requirements: list[str] = Field(default_factory=list)
    transition_intents: list[str] = Field(default_factory=list)


class ArtifactComparison(StrictModel):
    schema_version: int = 1
    comparison_id: str
    intent_id: str
    analysis_id: str
    dimensions: dict[str, dict[str, Any]]
    status: GateStatus
    evidence_refs: list[str] = Field(default_factory=list)


class RevisionFeedback(StrictModel):
    schema_version: int = 1
    finding_id: str
    severity: str
    layer: str
    target: str
    suggested_action: str
    evidence_refs: list[str] = Field(default_factory=list)


class VideoTask(StrictModel):
    schema_version: int = 1
    task_id: str
    operation_id: str
    task_type: str
    status: str = "PENDING"
    dependencies: list[str] = Field(default_factory=list)
    input_refs: list[str] = Field(default_factory=list)
    output_refs: list[str] = Field(default_factory=list)
    failure: str | None = None


class PreflightResult(StrictModel):
    status: str
    checks: dict[str, bool]
    errors: list[str] = Field(default_factory=list)
