"""Hevi StoryPlan 三层结构 Pydantic 模型与 JSON Schema 导出。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from pydantic import BaseModel, Field, field_validator


BEAT_KINDS = {"cause", "process", "result", "flashback", "flashforward"}
HOOK_TYPES = {"question", "conflict", "curiosity_image", "result_first"}
ROLL_ROLES = {"A_main", "B_support", "B_environment", "B_emotion", "B_transition"}
SHOT_TYPES = {"establishing", "character", "insert", "cutaway", "empty"}
SOURCE_KINDS = {"generated", "recorded", "existing", "screenshot"}
TRACK_KINDS = {"video", "voice", "music", "sfx", "subtitle"}
ASPECTS = {"16:9", "9:16", "1:1"}
NEW_INFO_REQUIRED_FIELDS = {"shot_id", "purpose", "start_state", "action", "end_state", "sound", "acceptance"}


class StoryBeat(BaseModel):
    beat_id: str
    phase: str = "process"  # cause / process / result / flashback
    summary: str = ""
    expectation: str = ""
    start_ms: int = 0
    end_ms: int = 0
    semantic_refs: list[str] = Field(default_factory=list)

    @field_validator("phase")
    @classmethod
    def validate_phase(cls, v: str) -> str:
        if v not in BEAT_KINDS:
            raise ValueError(f"invalid beat phase: {v}, must be in {BEAT_KINDS}")
        return v


class HookSpec(BaseModel):
    hook_type: str = "question"  # question / conflict / curiosity_image / result_first
    text: str = ""
    start_ms: int = 0
    end_ms: int = 3000
    shown_in: list[str] = Field(default_factory=lambda: ["voice", "subtitle", "visual"])

    @field_validator("hook_type")
    @classmethod
    def validate_hook_type(cls, v: str) -> str:
        if v not in HOOK_TYPES:
            raise ValueError(f"invalid hook type: {v}, must be in {HOOK_TYPES}")
        return v


class NarrativeLayer(BaseModel):
    hook: HookSpec = Field(default_factory=HookSpec)
    beats: list[StoryBeat] = Field(default_factory=list)
    closing_response: str = ""


class Shot(BaseModel):
    shot_id: str
    scene_id: str = "scene_1"
    sequence_id: int = 1
    purpose: str = ""  # 六项必填 1
    start_state: str = ""  # 六项必填 2
    action: str = ""  # 六项必填 3 (必须有明确结束状态)
    end_state: str = ""  # 六项必填 4 (必须有明确结束状态)
    sound: str = ""  # 六项必填 5
    acceptance: str = ""  # 六项必填 6
    roll_role: str = "A_main"  # A_main 或 B_*
    b_roll_function: str = ""  # 补充说明 | 交代环境 | 表达情绪 | 衔接
    shot_type: str = "character"  # establishing / character / insert / cutaway / empty
    material_source: str = "generated"  # generated / recorded / existing / screenshot
    new_info: list[str] = Field(default_factory=list)  # 这一镜新增的信息
    start_ms: int = 0
    end_ms: int = 0
    in_point_ms: int = 0
    out_point_ms: int = 0
    capability_binding: dict[str, Any] = Field(default_factory=dict)

    @field_validator("roll_role")
    @classmethod
    def validate_roll_role(cls, v: str) -> str:
        if v not in ROLL_ROLES:
            raise ValueError(f"invalid roll_role: {v}, must be in {ROLL_ROLES}")
        return v

    @field_validator("shot_type")
    @classmethod
    def validate_shot_type(cls, v: str) -> str:
        if v not in SHOT_TYPES:
            raise ValueError(f"invalid shot_type: {v}, must be in {SHOT_TYPES}")
        return v

    @field_validator("material_source")
    @classmethod
    def validate_material_source(cls, v: str) -> str:
        if v not in SOURCE_KINDS:
            raise ValueError(f"invalid material_source: {v}, must be in {SOURCE_KINDS}")
        return v


class Scene(BaseModel):
    scene_id: str = "scene_1"
    location: str = ""
    time_of_day: str = "day"
    shots: list[Shot] = Field(default_factory=list)


class Sequence(BaseModel):
    sequence_id: int = 1
    name: str = "main"
    scenes: list[Scene] = Field(default_factory=list)


class ShotLayer(BaseModel):
    sequences: list[Sequence] = Field(default_factory=list)


class TimelineClip(BaseModel):
    clip_id: str
    track_kind: str
    start_ms: int
    end_ms: int
    source_ref: str = ""
    text: str = ""

    model_config = {"frozen": True}


class TimelineTrack(BaseModel):
    track_kind: str = "video"
    clips: list[TimelineClip] = Field(default_factory=list)

    @field_validator("track_kind")
    @classmethod
    def validate_track_kind(cls, v: str) -> str:
        if v not in TRACK_KINDS:
            raise ValueError(f"invalid track kind: {v}, must be in {TRACK_KINDS}")
        return v


class TimelineLayer(BaseModel):
    duration_ms: int = 10000
    tracks: list[TimelineTrack] = Field(default_factory=list)


class StoryPlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: f"sp-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
    title: str = ""
    aspect: str = "16:9"
    fps: int = 30
    duration_sec: float = 10.0
    audience: str = "kids_2_6"
    language: str = "zh"
    narration_text: str = ""
    narrative: NarrativeLayer = Field(default_factory=NarrativeLayer)
    shots: ShotLayer = Field(default_factory=ShotLayer)
    timeline: TimelineLayer = Field(default_factory=TimelineLayer)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("aspect")
    @classmethod
    def validate_aspect(cls, v: str) -> str:
        if v not in ASPECTS:
            raise ValueError(f"invalid aspect: {v}, must be in {ASPECTS}")
        return v


def story_plan_schema() -> dict[str, Any]:
    return StoryPlan.model_json_schema()
