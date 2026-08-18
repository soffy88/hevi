from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

ProductionSource = Literal[
    "studio",
    "automatic",
    "tongjian",
    "shortdrama",
    "explainer",
    "presenter",
    "seedance",
    "clip_video",
    "voice_studio_tts",
    "director_graph",
    "lot",
]


class ExecutionBinding(BaseModel):
    """Immutable execution selection stored with newly created tasks."""

    capability_id: str
    adapter_version: str = "1"
    engine: str = "oservi.production_execution"
    engine_version: str = "compat"


class ProductionRequest(BaseModel):
    """One canonical handoff from a frontend/adapter to the execution layer."""

    source: ProductionSource
    topic: str = Field(min_length=1)
    duration_archetype: str = "1-5min"
    video_provider: str = "auto"
    audio_provider: str = "vibevoice"
    quality_profile: str = "standard"
    aspect_ratio: str = "9:16"
    budget_usd: float | None = Field(default=None, gt=0)
    num_characters: int = Field(default=1, ge=0)
    subject_ids: list[str] = Field(default_factory=list)
    presenter_id: str | None = None
    style_pack_id: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_subject_count(self) -> ProductionRequest:
        if self.subject_ids and self.num_characters < len(self.subject_ids):
            self.num_characters = len(self.subject_ids)
        return self

    def to_task_args(self) -> dict[str, Any]:
        """Compile the contract to the existing TaskService keyword boundary."""
        return {
            "topic": self.topic,
            "duration_archetype": self.duration_archetype,
            "video_provider": self.video_provider,
            "audio_provider": self.audio_provider,
            "quality_profile": self.quality_profile,
            "aspect_ratio": self.aspect_ratio,
            "num_characters": self.num_characters,
            "subject_id": self.subject_ids[0] if self.subject_ids else None,
            "character_subject_ids": self.subject_ids or None,
            "presenter_id": self.presenter_id,
            "style_pack_id": self.style_pack_id,
            "budget_usd": self.budget_usd,
            "production_source": self.source,
            **self.options,
        }
