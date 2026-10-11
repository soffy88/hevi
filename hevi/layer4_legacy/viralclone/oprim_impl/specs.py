"""Contracts, data schemas, and validation specs for ViralClone (oprim layer)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class WordToken:
    word: str
    start_s: float
    end_s: float
    score: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WordToken:
        return cls(
            word=str(data.get("word") or ""),
            start_s=float(data.get("start_s") or 0.0),
            end_s=float(data.get("end_s") or 0.0),
            score=float(data.get("score") or 1.0),
        )


@dataclass
class SubtitleBox:
    x0: float
    y0: float
    x1: float
    y1: float
    line_height_px: float
    avg_y_px: float
    relative_line_height: float
    text_sample: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SubtitleBox:
        return cls(
            x0=float(data.get("x0") or 0.0),
            y0=float(data.get("y0") or 0.0),
            x1=float(data.get("x1") or 0.0),
            y1=float(data.get("y1") or 0.0),
            line_height_px=float(data.get("line_height_px") or 0.0),
            avg_y_px=float(data.get("avg_y_px") or 0.0),
            relative_line_height=float(data.get("relative_line_height") or 0.0),
            text_sample=str(data.get("text_sample") or ""),
        )


@dataclass
class RhythmStats:
    total_duration_s: float
    shot_count: int
    first_shot_duration_s: float
    hook_duration_s: float
    mean_shot_duration_s: float
    median_shot_duration_s: float
    cuts_per_minute: float
    speech_rate_wps: float
    silence_intervals: list[dict[str, float]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RhythmStats:
        return cls(
            total_duration_s=float(data.get("total_duration_s") or 0.0),
            shot_count=int(data.get("shot_count") or 0),
            first_shot_duration_s=float(data.get("first_shot_duration_s") or 0.0),
            hook_duration_s=float(data.get("hook_duration_s") or 0.0),
            mean_shot_duration_s=float(data.get("mean_shot_duration_s") or 0.0),
            median_shot_duration_s=float(data.get("median_shot_duration_s") or 0.0),
            cuts_per_minute=float(data.get("cuts_per_minute") or 0.0),
            speech_rate_wps=float(data.get("speech_rate_wps") or 0.0),
            silence_intervals=list(data.get("silence_intervals") or []),
        )


@dataclass
class ReferenceBreakdown:
    source_video: str
    width: int
    height: int
    fps: float
    duration_s: float
    cut_timestamps_s: list[float]
    words: list[WordToken]
    sentences: list[dict[str, Any]]
    rhythm: RhythmStats
    subtitle_box: SubtitleBox | None = None
    semantic_roles: dict[str, Any] = field(default_factory=dict)
    semantic_visual: str = "UNKNOWN"
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_video": self.source_video,
            "width": self.width,
            "height": self.height,
            "fps": round(self.fps, 2),
            "duration_s": round(self.duration_s, 3),
            "cut_timestamps_s": [round(t, 3) for t in self.cut_timestamps_s],
            "words": [w.to_dict() for w in self.words],
            "sentences": self.sentences,
            "rhythm": self.rhythm.to_dict(),
            "subtitle_box": self.subtitle_box.to_dict() if self.subtitle_box else None,
            "semantic_roles": self.semantic_roles,
            "semantic_visual": self.semantic_visual,
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReferenceBreakdown:
        sub = data.get("subtitle_box")
        return cls(
            source_video=str(data.get("source_video") or ""),
            width=int(data.get("width") or 0),
            height=int(data.get("height") or 0),
            fps=float(data.get("fps") or 25.0),
            duration_s=float(data.get("duration_s") or 0.0),
            cut_timestamps_s=[float(t) for t in data.get("cut_timestamps_s") or []],
            words=[WordToken.from_dict(w) for w in data.get("words") or []],
            sentences=list(data.get("sentences") or []),
            rhythm=RhythmStats.from_dict(data.get("rhythm") or {}),
            subtitle_box=SubtitleBox.from_dict(sub) if sub else None,
            semantic_roles=dict(data.get("semantic_roles") or {}),
            semantic_visual=str(data.get("semantic_visual") or "UNKNOWN"),
            provenance=dict(data.get("provenance") or {}),
        )


@dataclass
class VisualAnchor:
    event_type: str  # "cut", "product_card", "broll", "sticker", "effect"
    sentence_idx: int = 0
    word_offset_idx: int = 0  # index within sentence
    relative_delay_s: float = 0.0
    duration_s: float = 2.0
    target_slot: str = ""  # slot key if dynamic
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TemplateSegment:
    segment_id: str
    role: str  # "hook", "selling_point", "proof", "cta"
    narration_slot: str  # slot key in input variables
    anchors: list[VisualAnchor] = field(default_factory=list)
    caption_style: str = "karaoke"

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "role": self.role,
            "narration_slot": self.narration_slot,
            "anchors": [a.to_dict() for a in self.anchors],
            "caption_style": self.caption_style,
        }


@dataclass
class TemplateSpec:
    template_id: str
    version: str = "viralclone-v1"
    aspect_ratio: str = "9:16"
    width: int = 720
    height: int = 1280
    fps: int = 25
    rhythm_archetype: str = "fast_hook"
    segments: list[TemplateSegment] = field(default_factory=list)
    slots_schema: dict[str, str] = field(default_factory=dict)
    default_slots: dict[str, Any] = field(default_factory=dict)
    visual_rules: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "version": self.version,
            "aspect_ratio": self.aspect_ratio,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "rhythm_archetype": self.rhythm_archetype,
            "segments": [s.to_dict() for s in self.segments],
            "slots_schema": self.slots_schema,
            "default_slots": self.default_slots,
            "visual_rules": self.visual_rules,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TemplateSpec:
        segs: list[TemplateSegment] = []
        for s in data.get("segments") or []:
            anchors = [
                VisualAnchor(
                    event_type=str(a.get("event_type") or "cut"),
                    sentence_idx=int(a.get("sentence_idx") or 0),
                    word_offset_idx=int(a.get("word_offset_idx") or 0),
                    relative_delay_s=float(a.get("relative_delay_s") or 0.0),
                    duration_s=float(a.get("duration_s") or 2.0),
                    target_slot=str(a.get("target_slot") or ""),
                    parameters=dict(a.get("parameters") or {}),
                )
                for a in s.get("anchors") or []
            ]
            segs.append(
                TemplateSegment(
                    segment_id=str(s.get("segment_id") or ""),
                    role=str(s.get("role") or "hook"),
                    narration_slot=str(s.get("narration_slot") or ""),
                    anchors=anchors,
                    caption_style=str(s.get("caption_style") or "karaoke"),
                )
            )
        return cls(
            template_id=str(data.get("template_id") or "tpl_viral_default"),
            version=str(data.get("version") or "viralclone-v1"),
            aspect_ratio=str(data.get("aspect_ratio") or "9:16"),
            width=int(data.get("width") or 720),
            height=int(data.get("height") or 1280),
            fps=int(data.get("fps") or 25),
            rhythm_archetype=str(data.get("rhythm_archetype") or "fast_hook"),
            segments=segs,
            slots_schema=dict(data.get("slots_schema") or {}),
            default_slots=dict(data.get("default_slots") or {}),
            visual_rules=dict(data.get("visual_rules") or {}),
        )


@dataclass
class WatermarkSpec:
    text: str = "AI生成"
    font_size_px: int = 36
    duration_s: float = 2.5
    position: str = "top_left"
    ratio_to_short_edge: float = 0.05
    implicit_comment: str = "Hevi ViralClone 3O Generator; GB 45438-2025 AI-Generated Content"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DiversityRecord:
    pair: list[str]
    phash_distance: int
    phash_similarity: float
    text_similarity: float
    passed: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_template_spec(spec: TemplateSpec, *, allow_empty: bool = False) -> list[str]:
    errors: list[str] = []
    if not spec.template_id:
        errors.append("missing_template_id")
    if spec.width <= 0 or spec.height <= 0:
        errors.append("invalid_resolution")
    if not allow_empty and not spec.segments:
        errors.append("no_segments")
    for idx, seg in enumerate(spec.segments):
        if not seg.segment_id:
            errors.append(f"segment_{idx}_missing_id")
        if not seg.narration_slot:
            errors.append(f"segment_{idx}_missing_slot")
    return errors


def validate_watermark_spec(spec: WatermarkSpec, *, frame_short_edge: int = 720) -> list[str]:
    errors: list[str] = []
    if not spec.text:
        errors.append("missing_watermark_text")
    if spec.duration_s < 2.0:
        errors.append("duration_under_2s")
    required_min_px = frame_short_edge * 0.05
    if spec.font_size_px < required_min_px:
        errors.append(f"font_size_{spec.font_size_px}_under_5pct_{required_min_px}")
    return errors
