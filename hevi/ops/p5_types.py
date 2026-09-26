"""HEVI P5 — Content Factory canonical types.

ContentRequest → ProductionJob → ProductionMission → Profile → Quality → Correctness.
All production flows through existing P0-P4 pipeline. No second pipeline/authority/registry.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _cid() -> str:
    return f"cid-{uuid4().hex[:12]}"


# ── Enums ───────────────────────────────────────────────────────────────

class ContentStatus(StrEnum):
    CREATED = "CREATED"
    RESEARCHING = "RESEARCHING"
    SCRIPTING = "SCRIPTING"
    TOPIC_APPROVAL = "TOPIC_APPROVAL"
    SCRIPT_APPROVAL = "SCRIPT_APPROVAL"
    TTS = "TTS"
    VISUAL_PRODUCTION = "VISUAL_PRODUCTION"
    PROOF_APPROVAL = "PROOF_APPROVAL"
    FINAL_RENDER = "FINAL_RENDER"
    FINAL_APPROVAL = "FINAL_APPROVAL"
    DELIVERING = "DELIVERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    WAITING_APPROVAL = "WAITING_APPROVAL"


class ApprovalType(StrEnum):
    TOPIC = "TOPIC"
    SCRIPT = "SCRIPT"
    PROOF = "PROOF"
    FINAL = "FINAL"


class ApprovalPolicy(StrEnum):
    REQUIRED = "REQUIRED"
    AUTO_IF_CONFIDENT = "AUTO_IF_CONFIDENT"
    SKIP = "SKIP"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    CANCELLED = "CANCELLED"


class SourceKind(StrEnum):
    QUOTE = "QUOTE"
    PARAPHRASE = "PARAPHRASE"
    ORIGINAL_COMMENTARY = "ORIGINAL_COMMENTARY"


class VisualProvenance(StrEnum):
    REAL = "REAL"
    ARCHIVAL = "ARCHIVAL"
    OFFICIAL = "OFFICIAL"
    GENERATED = "GENERATED"
    SYMBOLIC = "SYMBOLIC"


class Platform(StrEnum):
    YOUTUBE = "YOUTUBE"
    BILIBILI = "BILIBILI"
    TIKTOK = "TIKTOK"
    DOUYIN = "DOUYIN"
    INSTAGRAM = "INSTAGRAM"
    XIAOHONGSHU = "XIAOHONGSHU"
    GENERIC = "GENERIC"


# ── Core Data Classes ───────────────────────────────────────────────────

@dataclass
class BookSourceBundle:
    """Verified book source with facts, quotes, and paraphrases."""
    book_title: str
    author: str
    edition: str = ""
    isbn: str = ""
    publisher: str = ""
    cover_source: str = ""  # URL or local path with hash
    cover_hash: str = ""
    verified_facts: list[str] = field(default_factory=list)
    verified_quotes: list[tuple[str, str]] = field(default_factory=list)  # (quote, location)
    paraphrased_ideas: list[str] = field(default_factory=list)
    source_references: list[str] = field(default_factory=list)  # page/chapter references
    classification: dict[str, SourceKind] = field(default_factory=dict)  # text -> kind

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContentScript:
    """Formal script artifact with emotional structure."""
    script_id: str
    content_id: str
    revision: int = 1
    book_source: BookSourceBundle | None = None
    hook: str = ""
    situation: str = ""
    emotional_recognition: str = ""
    book_entry: str = ""  # book title anchor with pause
    idea_development: str = ""
    emotional_turn: str = ""
    payoff: str = ""
    ending_question: str = ""
    full_text: str = ""  # concatenated for TTS
    target_duration_s: float = 180.0
    target_chars_per_second: float = 4.56  # Chinese chars/sec
    pause_policy: dict[str, float] = field(default_factory=lambda: {
        "book_title": 0.8,
        "paragraph": 0.5,
        "emotional": 1.0,
    })

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.book_source:
            d["book_source"] = self.book_source.to_dict()
        return d


@dataclass
class ApprovalRequest:
    """Durable human approval gate."""
    approval_id: str
    content_id: str
    type: ApprovalType
    revision: int
    artifact_refs: dict[str, str] = field(default_factory=dict)  # name -> path/hash
    reason: str = ""
    risk_flags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    status: ApprovalStatus = ApprovalStatus.PENDING
    decided_at: str = ""
    decided_by: str = ""
    decision_reason: str = ""

    def is_terminal(self) -> bool:
        return self.status in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED, ApprovalStatus.CANCELLED)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ApprovalPolicySet:
    """Per-production approval configuration."""
    topic: ApprovalPolicy = ApprovalPolicy.AUTO_IF_CONFIDENT
    script: ApprovalPolicy = ApprovalPolicy.REQUIRED
    proof: ApprovalPolicy = ApprovalPolicy.REQUIRED
    final: ApprovalPolicy = ApprovalPolicy.REQUIRED

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VoiceProfile:
    """Canonical voice configuration for TTS."""
    voice_profile_id: str
    provider: str  # "volcano", "edge_tts", etc.
    provider_voice_id: str
    language: str = "zh-CN"
    speed_policy: dict[str, float] = field(default_factory=lambda: {"default": 1.0})
    status: str = "active"  # active, deprecated, testing
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VoicePerformance:
    """Single continuous TTS output with provenance."""
    performance_id: str
    content_id: str
    voice_profile_id: str
    script_revision: int
    audio_path: str
    audio_hash: str
    duration_s: float
    actual_chars_per_second: float
    provider_request_id: str = ""
    provider_latency_s: float = 0.0
    cost_usd: float = 0.0
    asr_aligned: bool = False
    asr_coverage: float = 0.0
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProductionAsset:
    """Versioned production asset with provenance."""
    asset_id: str
    type: str  # book_cover, intro, calligraphy, bgm, transition, caption_font, sticker
    path: str
    hash: str
    license: str = ""
    source: str = ""
    version: str = "1.0"
    provenance: VisualProvenance = VisualProvenance.GENERATED
    book_identity: str = ""  # for book covers
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProductionAssetPack:
    """Curated asset pack for a production line."""
    pack_id: str
    pack_version: str
    assets: list[ProductionAsset] = field(default_factory=list)
    description: str = ""

    def get_asset(self, asset_id: str) -> ProductionAsset | None:
        return next((a for a in self.assets if a.asset_id == asset_id), None)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MusicPolicy:
    """Music mix configuration."""
    track: str = ""
    source: str = ""
    license: str = ""
    gain_db: float = -18.0
    ducking_policy: str = "aggressive"  # aggressive, moderate, none
    fade_in_s: float = 1.0
    fade_out_s: float = 2.0
    required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AudioMixManifest:
    """Record of audio mixing decisions."""
    voice_gain_db: float = 0.0
    music_gain_db: float = -18.0
    ducking_applied: bool = True
    final_loudness_lufs: float = -16.0
    master_audio_path: str = ""
    voice_performance_ref: str = ""
    music_policy: MusicPolicy | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.music_policy:
            d["music_policy"] = self.music_policy.to_dict()
        return d


@dataclass
class CaptionStyleProfile:
    """Reusable caption styling."""
    font: str = "Noto Sans SC"
    size_px: int = 48
    position: str = "bottom"
    max_lines: int = 2
    safe_area_pct: float = 0.9
    punctuation_policy: str = "preserve"  # preserve, simplify
    outline_px: int = 2
    color: str = "#FFFFFF"
    background: str = "rgba(0,0,0,0.6)"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContentFingerprint:
    """Content identity for deduplication and reproducibility."""
    content_id: str
    book_topic: str
    situation: str
    emotion: str
    argument: str
    script_hash: str
    voice_hash: str
    visual_plan_hash: str
    template_version: str = ""
    voice_profile_version: str = ""
    asset_pack_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContentQualityReport:
    """Aggregated quality report (no second QA authority)."""
    content_id: str
    source_truth: bool = False
    script_quality: bool = False
    voice_alignment: bool = False
    voice_pacing: bool = False
    visual_grounding: bool = False
    visual_progression: bool = False
    caption_sync: bool = False
    music_mix: bool = False
    profile_quality: bool = False
    final_qa: bool = False
    gates: dict[str, bool] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def overall_pass(self) -> bool:
        return all([
            self.source_truth, self.script_quality, self.voice_alignment,
            self.voice_pacing, self.visual_grounding, self.visual_progression,
            self.caption_sync, self.music_mix, self.profile_quality, self.final_qa
        ])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CostReport:
    """Per-content and batch cost accounting."""
    content_id: str = ""
    research_usd: float = 0.0
    llm_usd: float = 0.0
    tts_usd: float = 0.0
    visual_usd: float = 0.0
    render_usd: float = 0.0
    delivery_usd: float = 0.0
    total_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BatchCostSummary:
    """Batch-level cost summary."""
    batch_id: str
    total_usd: float = 0.0
    cost_per_video_usd: float = 0.0
    cost_per_video_minute_usd: float = 0.0
    items: list[CostReport] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EditableProjectManifest:
    """Editable project delivery manifest (Jianying/CapCut)."""
    project_type: str  # "jianying", "capcut"
    project_path: str
    timeline_json: str = ""
    audio_refs: list[str] = field(default_factory=list)
    video_image_refs: list[str] = field(default_factory=list)
    caption_refs: list[str] = field(default_factory=list)
    font_refs: list[str] = field(default_factory=list)
    music_refs: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    artifact_hashes: dict[str, str] = field(default_factory=dict)
    validation_passed: bool = False
    validation_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContentRequest:
    """Top-level content production request."""
    content_id: str = field(default_factory=_cid)
    topic: str = ""
    profile_id: str = "EMOTIONAL_BOOK_REVIEW"
    audience: str = ""
    target_duration_s: float = 180.0
    platform: Platform = Platform.GENERIC
    language: str = "zh-CN"
    creative_brief: str = ""
    source_policy: dict[str, Any] = field(default_factory=dict)
    voice_policy: dict[str, Any] = field(default_factory=dict)
    visual_policy: dict[str, Any] = field(default_factory=dict)
    music_policy: dict[str, Any] = field(default_factory=dict)
    approval_policy: ApprovalPolicySet = field(default_factory=ApprovalPolicySet)
    delivery_policy: dict[str, Any] = field(default_factory=dict)
    budget_usd: float = 50.0
    priority: int = 5
    book_source: BookSourceBundle | None = None
    created_at: str = field(default_factory=_now)
    template_version: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_production_job(self) -> Any:
        """Convert to P4 ProductionJob for scheduling."""
        from hevi.ops.p4_types import ProductionJob as P4ProductionJob
        narration = self._extract_narration()
        return P4ProductionJob(
            job_id=self.content_id,
            profile_id=self.profile_id,
            topic=self.topic,
            narration=narration,
            priority=self.priority,
            book_meta={
                "title": self.book_source.book_title if self.book_source else "",
                "author": self.book_source.author if self.book_source else "",
                "verified": bool(self.book_source and self.book_source.verified_facts),
                "note": "PARAPHRASE" if self.book_source else "",
            },
            estimated_cost_usd=self.budget_usd,
            segments=1,
        )

    def _extract_narration(self) -> str:
        """Extract full narration from script or creative brief."""
        if self.creative_brief:
            return self.creative_brief
        return self.topic

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.book_source:
            d["book_source"] = self.book_source.to_dict()
        return d


@dataclass
class ContentItem:
    """Runtime content item with full lifecycle state."""
    content_id: str
    request: ContentRequest
    status: ContentStatus = ContentStatus.CREATED
    script: ContentScript | None = None
    voice_performance: VoicePerformance | None = None
    approvals: dict[ApprovalType, ApprovalRequest] = field(default_factory=dict)
    visual_assets: list[ProductionAsset] = field(default_factory=list)
    audio_mix: AudioMixManifest | None = None
    caption_style: CaptionStyleProfile | None = None
    final_mp4: str = ""
    proof_mp4: str = ""
    captions_srt: str = ""
    editable_project: EditableProjectManifest | None = None
    delivery_receipt: str = ""
    quality_report: ContentQualityReport | None = None
    cost_report: CostReport | None = None
    fingerprint: ContentFingerprint | None = None
    current_revision: int = 1
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    error: str = ""
    blockers: list[str] = field(default_factory=list)

    def can_proceed(self) -> bool:
        if self.status in (ContentStatus.COMPLETED, ContentStatus.FAILED, ContentStatus.CANCELLED):
            return False
        if self.status == ContentStatus.WAITING_APPROVAL:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["request"] = self.request.to_dict()
        if self.script:
            d["script"] = self.script.to_dict()
        if self.voice_performance:
            d["voice_performance"] = self.voice_performance.to_dict()
        d["approvals"] = {k.value: v.to_dict() for k, v in self.approvals.items()}
        if self.audio_mix:
            d["audio_mix"] = self.audio_mix.to_dict()
        if self.editable_project:
            d["editable_project"] = self.editable_project.to_dict()
        if self.quality_report:
            d["quality_report"] = self.quality_report.to_dict()
        if self.cost_report:
            d["cost_report"] = self.cost_report.to_dict()
        if self.fingerprint:
            d["fingerprint"] = self.fingerprint.to_dict()
        return d


# ── Factory Types ───────────────────────────────────────────────────────

@dataclass
class ContentFactoryRequest:
    """Batch content factory request."""
    batch_id: str = field(default_factory=lambda: f"batch-{uuid4().hex[:8]}")
    items: list[ContentRequest] = field(default_factory=list)
    concurrency_limit: int = 2
    budget_usd: float = 100.0
    priority: int = 5
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TopicCandidate:
    """Autonomous topic selection candidate."""
    candidate_id: str = field(default_factory=lambda: f"tc-{uuid4().hex[:8]}")
    book_title: str = ""
    author: str = ""
    situation: str = ""
    emotion: str = ""
    hook: str = ""
    reason: str = ""
    source_confidence: float = 0.0
    source_url: str = ""
    selected: bool = False
    selection_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Type Validation ─────────────────────────────────────────────────────

def validate_content_request(req: ContentRequest) -> list[str]:
    """Validate ContentRequest, return list of errors (empty = valid)."""
    errors = []
    if not req.topic:
        errors.append("topic required")
    if not req.profile_id:
        errors.append("profile_id required")
    if req.target_duration_s <= 0:
        errors.append("target_duration_s must be positive")
    if req.budget_usd <= 0:
        errors.append("budget_usd must be positive")
    if req.profile_id == "EMOTIONAL_BOOK_REVIEW":
        if not req.book_source or not req.book_source.book_title:
            errors.append("EMOTIONAL_BOOK_REVIEW requires book_source with title")
        if not req.book_source or not req.book_source.author:
            errors.append("EMOTIONAL_BOOK_REVIEW requires book_source with author")
        if not req.book_source or not req.book_source.verified_facts:
            errors.append("EMOTIONAL_BOOK_REVIEW requires verified_facts")
    return errors


def validate_book_source(bundle: BookSourceBundle) -> list[str]:
    """Validate BookSourceBundle for truth gate."""
    errors = []
    if not bundle.book_title:
        errors.append("book_title required")
    if not bundle.author:
        errors.append("author required")
    if not bundle.verified_facts:
        errors.append("verified_facts required (at least 1)")
    if not bundle.verified_quotes and not bundle.paraphrased_ideas:
        errors.append("at least verified_quotes or paraphrased_ideas required")
    if not bundle.cover_hash and bundle.cover_source:
        errors.append("cover_hash required when cover_source provided")
    return errors


def validate_voice_pacing(performance: VoicePerformance, target_cps: float = 4.56, tolerance: float = 0.15) -> bool:
    """Check if voice pacing is within tolerance."""
    if target_cps <= 0:
        return False
    error = abs(performance.actual_chars_per_second - target_cps) / target_cps
    return error <= tolerance


def validate_caption_audio_alignment(caption_srt: str, audio_path: str) -> tuple[bool, str]:
    """Validate caption timing against real audio (placeholder for ASR alignment check)."""
    # Real implementation would use ASR timestamps
    return True, ""


def validate_editable_project(manifest: EditableProjectManifest) -> tuple[bool, list[str]]:
    """Validate editable project structure."""
    errors = []
    if not manifest.project_path:
        errors.append("project_path required")
    if not manifest.timeline_json:
        errors.append("timeline_json required")
    if manifest.duration_s <= 0:
        errors.append("duration_s must be positive")
    for ref in manifest.audio_refs + manifest.video_image_refs + manifest.caption_refs + manifest.font_refs + manifest.music_refs:
        if not ref:
            errors.append(f"empty reference found")
    return len(errors) == 0, errors


__all__ = [
    # Enums
    "ContentStatus",
    "ApprovalType",
    "ApprovalPolicy",
    "ApprovalStatus",
    "SourceKind",
    "VisualProvenance",
    "Platform",
    # Core types
    "BookSourceBundle",
    "ContentScript",
    "ApprovalRequest",
    "ApprovalPolicySet",
    "VoiceProfile",
    "VoicePerformance",
    "ProductionAsset",
    "ProductionAssetPack",
    "MusicPolicy",
    "AudioMixManifest",
    "CaptionStyleProfile",
    "ContentFingerprint",
    "ContentQualityReport",
    "CostReport",
    "BatchCostSummary",
    "EditableProjectManifest",
    "ContentRequest",
    "ContentItem",
    # Factory types
    "ContentFactoryRequest",
    "TopicCandidate",
    # Validation
    "validate_content_request",
    "validate_book_source",
    "validate_voice_pacing",
    "validate_caption_audio_alignment",
    "validate_editable_project",
]