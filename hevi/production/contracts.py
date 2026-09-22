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
    "localize_video",
    "mpt",
    "voice_studio_tts",
    "director_graph",
    "lot",
    "local_media",
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


from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import ClassVar

PRODUCTION_STATUSES = frozenset({"pending", "running", "completed", "blocked", "failed", "cancelled"})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class ProductionResult:
    """Canonical result envelope shared by all Studio production lines."""

    run_id: str
    line_id: str
    status: str = "pending"
    input_manifest: dict[str, Any] = field(default_factory=dict)
    recipe_id: str = ""
    recipe_version: str = "1"
    stage_trace: list[dict[str, Any]] = field(default_factory=list)
    provider_trace: list[dict[str, Any]] = field(default_factory=list)
    artifact_manifest: dict[str, Any] = field(default_factory=dict)
    result_video_path: str | None = None
    quality_report: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=utc_now)
    completed_at: str | None = None
    failure: dict[str, Any] | None = None

    STATUSES: ClassVar[frozenset[str]] = PRODUCTION_STATUSES

    def __post_init__(self) -> None:
        if self.status not in PRODUCTION_STATUSES:
            raise ValueError(f"invalid production status: {self.status}")
        if self.status == "completed" and not self.completion_valid:
            raise ValueError("completed production result failed the completion contract")

    @property
    def completion_valid(self) -> bool:
        return bool(self.result_video_path and self.artifact_manifest.get("verified") is True and self.quality_report.get("passed") is True and self.provenance)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProductionResult":
        fields = {"run_id", "line_id", "status", "input_manifest", "recipe_id", "recipe_version", "stage_trace", "provider_trace", "artifact_manifest", "result_video_path", "quality_report", "provenance", "started_at", "completed_at", "failure"}
        return cls(**{key: payload[key] for key in fields if key in payload})


def completion_failure(result: dict[str, Any]) -> str | None:
    if result.get("status") != "completed":
        return f"status={result.get('status')!r}"
    if not result.get("result_video_path"):
        return "result_video_path missing"
    if (result.get("artifact_manifest") or {}).get("verified") is not True:
        return "artifact_manifest.verified is not true"
    if (result.get("quality") or result.get("quality_report") or {}).get("passed") is not True:
        return "quality gate did not pass"
    if not (result.get("provenance") or result.get("provenance_complete")):
        return "provenance incomplete"
    return None
