"""Stable data contracts for HEVI Shot Intelligence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SHOT_PLAN_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class CameraMotion:
    name: str = "static"
    speed: str = "medium"
    direction: str | None = None


@dataclass(frozen=True)
class Composition:
    name: str = "centered"
    subject_position: str = "center"
    safe_area: str = "standard"


@dataclass(frozen=True)
class TransitionIntent:
    name: str = "cut"
    compatible_with: tuple[str, ...] = ("cut", "dissolve", "match")


@dataclass(frozen=True)
class AestheticProfile:
    style: str = "natural"
    palette: str | None = None
    texture: str | None = None


@dataclass(frozen=True)
class BeatCue:
    time_s: float
    kind: str = "beat"
    strength: float = 1.0
    # G0.2-A2:稳定身份,供 Decision→Cue→Shot 追踪。空 = 老数据未补 ID(向后兼容)。
    cue_id: str = ""
    # P10 adapter 回指(CreativeCue id);无 creative 上游时为空,不影响现有行为。
    creative_cue_ref: str = ""


@dataclass(frozen=True)
class ShotRecipe:
    id: str
    shot_type: str
    framing: str
    subject_count: int = 1
    camera_motion: CameraMotion = field(default_factory=CameraMotion)
    lens_intent: str = "normal perspective"
    composition: Composition = field(default_factory=Composition)
    duration_range_s: tuple[float, float] = (1.0, 6.0)
    transition: TransitionIntent = field(default_factory=TransitionIntent)
    dialogue_compatible: bool = True
    narration_compatible: bool = True
    music_compatible: bool = True
    text_overlay_compatible: bool = True
    renderer_capabilities: tuple[str, ...] = ("remotion", "ffmpeg", "generated_video")
    constraints: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    provenance: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ShotIntent:
    line: str
    scene_intent: str
    narrative_purpose: str
    subject: str
    dialogue_present: bool = False
    narration_present: bool = False
    target_duration_s: float = 3.0
    aspect_ratio: str = "16:9"
    pacing: str = "medium"
    style: str = "natural"
    available_providers: tuple[str, ...] = ()
    available_assets: tuple[str, ...] = ()
    beat_map: tuple[BeatCue, ...] = ()


@dataclass(frozen=True)
class ShotPlan:
    line: str
    shots: tuple[ShotRecipe, ...]
    beat_cues: tuple[BeatCue, ...] = ()
    diagnostics: tuple[str, ...] = ()
    canonical: bool = True
    shot_plan_schema_version: str = SHOT_PLAN_SCHEMA_VERSION


@dataclass(frozen=True)
class ShotSelectionResult:
    selected: ShotRecipe
    confidence: float
    rationale: str
    alternatives: tuple[ShotRecipe, ...] = ()
    renderer_projection: dict[str, Any] = field(default_factory=dict)
    validation_constraints: tuple[str, ...] = ()
