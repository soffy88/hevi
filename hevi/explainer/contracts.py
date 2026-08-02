"""Explainer Master v8 contracts.

The research and assembly endpoints intentionally use a small, explicit
contract.  The UI can edit the visual scaffold without knowing anything about
the provider implementation, while the task adapter keeps the durable task
and artifact semantics that the rest of HEVI already uses.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

VisualType = Literal[
    "heygen_avatar",
    "broll_news",
    "browser_broll",
    "broll_stock",
    "data_screenshot",
    "remotion_chart",
    "remotion_code",
    "voiceover",
]


class ExplainerResearchRequest(BaseModel):
    topic_or_url: str = Field(min_length=1, max_length=20_000)
    voice_profile: str = "cosyvoice_default"
    heygen_presenter_id: str | None = None

    @field_validator("topic_or_url")
    @classmethod
    def topic_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("topic_or_url 不能为空")
        return value


class ResearchFact(BaseModel):
    claim: str
    source: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class HookDraft(BaseModel):
    text: str
    angle: str = ""
    recommended: bool = False


class ExplainerCue(BaseModel):
    time_range: str = Field(min_length=3, max_length=32)
    visual_type: VisualType
    text: str = Field(min_length=1, max_length=2_000)
    visual_config: dict[str, Any] = Field(default_factory=dict)
    step_id: int | None = None
    time_estimate_s: float | None = Field(default=None, gt=0, le=300)
    target_url: str | None = None
    highlight_selector: str | None = None
    chart_data: dict[str, Any] | None = None
    code_text: str | None = None
    language: str | None = None

    @field_validator("time_range")
    @classmethod
    def validate_time_range(cls, value: str) -> str:
        value = value.strip()
        if "-" not in value:
            raise ValueError("time_range 必须是 MM:SS-MM:SS")
        return value


class ExplainerScriptDraft(BaseModel):
    id: str = ""
    version_id: str | None = None
    title: str
    viewpoint: str = ""
    hook: str = ""
    cues: list[ExplainerCue] = Field(min_length=1)

    @model_validator(mode="after")
    def fill_version_id(self) -> ExplainerScriptDraft:
        if not self.id:
            self.id = self.version_id or "script"
        if self.version_id is None:
            self.version_id = self.id
        return self


class ExplainerResearchResponse(BaseModel):
    topic_or_url: str
    research_summary: str = ""
    facts: list[ResearchFact] = Field(default_factory=list)
    hooks: list[HookDraft | str] = Field(min_length=5, max_length=5)
    hook_details: list[HookDraft] = Field(default_factory=list)
    scripts: list[ExplainerScriptDraft] = Field(min_length=3, max_length=3)
    script_versions: list[ExplainerScriptDraft] = Field(default_factory=list)
    provider: str
    decision_trail: list[dict[str, Any]] = Field(default_factory=list)


class ExplainerAssembleRequest(BaseModel):
    # The v6 wire contract only requires the approval payload.  The topic is
    # optional because the research session may already be persisted server
    # side; clients that keep it locally can still send it for traceability.
    topic_or_url: str = Field(default="", max_length=20_000)
    voice_profile: str = "cosyvoice_default"
    heygen_presenter_id: str | None = None
    selected_hook: str = Field(min_length=1, max_length=500)
    final_script_cues: list[ExplainerCue] = Field(min_length=1)
    enable_remotion_code_render: bool = True
    enable_circle_avatar_mask: bool = True
    enable_browser_broll: bool = True
    aspect_ratio: Literal["9:16", "16:9"] = "9:16"


class ExplainerAssemblyAccepted(BaseModel):
    task_id: str
    status: str
    estimated_seconds: int = 90
    sse_channel: str = ""
    production_source: str = "explainer"
    engine_version: str
    adapter_version: str


class ExplainerCapabilityError(RuntimeError):
    """A provider or required production capability is not configured."""

    def __init__(self, code: str, message: str, *, action: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action


class ExplainerServiceResult(BaseModel):
    """Internal shape returned by a research provider before API projection."""

    model_config = ConfigDict(extra="allow")

    facts: list[ResearchFact]
    research_summary: str = ""
    hooks: list[HookDraft]
    scripts: list[ExplainerScriptDraft]
    provider: str
    decision_trail: list[dict[str, Any]] = Field(default_factory=list)
