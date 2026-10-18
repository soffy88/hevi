"""Shared Pydantic models for Hevi video generation oskill."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel


class Scene(BaseModel):
    """A single scene in a video script."""

    index: int
    narration: str
    duration_s: float
    visual_description: str


class Script(BaseModel):
    """Video script output from script_writer."""

    title: str
    description: str
    scenes: list[Scene]
    estimated_duration_s: float


class Shot(BaseModel):
    """A single shot in a storyboard."""

    shot_id: str
    scene_index: int
    visual_description: str
    narration: str
    duration_s: float
    importance: int = 0
    motion: str | None = None


class Storyboard(BaseModel):
    """Storyboard output from storyboard_planner."""

    shots: list[Shot]


class ShotPlan(BaseModel):
    """Per-shot generation plan."""

    shot_id: str
    image_prompt: str
    tts_text: str
    duration_s: float


class ConsistencyIssue(BaseModel):
    """A single consistency issue found."""

    shot_id: str
    description: str
    severity: str = "medium"


class ConsistencyReport(BaseModel):
    """Consistency check output."""

    issues: list[ConsistencyIssue]
    overall_score: float


class ReferenceDescription(BaseModel):
    """Detailed image generation prompt for a shot."""

    shot_id: str
    detailed_prompt: str
    style_tags: list[str]


class MetadataConstraints(BaseModel):
    """Platform-agnostic metadata constraints."""

    title_max_chars: int
    description_max_chars: int
    tags_max_count: int
    tag_max_chars: int


class Metadata(BaseModel):
    """Generated metadata output."""

    title: str
    description: str
    tags: list[str]
    topics: list[str]


class InsightContext(BaseModel):
    """Output from threeo_ingester."""

    topic: str
    key_findings: list[str]
    charts: list[dict[str, object]]
    related_concepts: list[str]
    source_omodul: str
    raw_report: dict[str, object]


class SubjectRef(BaseModel):
    """Reference to a subject/character for LLM prompt injection.

    Used by script_writer, storyboard_planner, and multi_shot_storyboard_workflow
    to inject character context into LLM prompts.
    """

    subject_id: str
    name: str
    description: str = ""  # optional; injected into LLM prompt when non-empty
    image_path: Path | None = None  # optional reference image


# ── hevi-v2 types (added v3.18.0) ──────────────────────────────────────────


class SpeakerLine(BaseModel):
    """One speaker's line in a multi-speaker script."""

    speaker_id: str
    text: str
    voice_ref: Path | None = None  # zero-shot clone reference; None = default voice


class ShotFrame(BaseModel):
    """A generated video frame recorded in the timeline history."""

    shot_id: str
    scene_id: str
    timeline_index: int  # ordering across the full timeline
    frame_path: Path
    characters_present: list[str]
    environment_id: str


class ReferenceSet(BaseModel):
    """Selected reference frames for a shot (output of select_reference)."""

    character_refs: dict[str, Path]  # character_id → best reference frame
    environment_refs: dict[str, Path]
    selected_from: list[str]  # source shot_ids (traceability)


class FrameConsistencyResult(BaseModel):
    """VLM visual consistency evaluation of candidate frames."""

    best_frame: Path
    scores: dict[str, float]  # frame_path str → consistency score [0, 1]
    passed: bool  # best score ≥ threshold in criteria


class Chapter(BaseModel):
    """A chapter in a long-form video script."""

    chapter_id: str
    title: str
    scenes: list[dict]  # scene descriptors (flexible for multi-genre)
    dialogues: list[SpeakerLine]


class ChapterScript(BaseModel):
    """Multi-chapter script output from script_writer(chapter_mode=True)."""

    chapters: list[Chapter]
    total_duration_s: float
    characters: list[str]
