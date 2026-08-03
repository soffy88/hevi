"""Explainer Master v8 contracts.

The research and assembly endpoints intentionally use a small, explicit
contract.  The UI can edit the visual scaffold without knowing anything about
the provider implementation, while the task adapter keeps the durable task
and artifact semantics that the rest of HEVI already uses.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

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
    """Legacy single-choice hook (v8 wire compat only).

    Kept for parsing old provider output; new research must emit
    :class:`HookNode` matrix nodes instead.  The ``recommended`` label is
    deliberately deprecated — v9 prompts forbid it and no UI shows it.
    """

    text: str
    angle: str = ""
    recommended: bool = False


HookNarrativeFunction = Literal[
    "opening_suspense",  # 开场总悬念
    "mid_conflict",  # 中段转折/冲突点
    "climax_breakthrough",  # 高潮解答
]


class HookNode(BaseModel):
    """递进式 Hook 矩阵节点 —— v9 取代浅薄的“开场 5 选 1”。

    LLM 必须从主题知识图谱的关键节点产出,每个 Hook 绑定一个叙事功能档位
    (opening_suspense → mid_conflict → climax_breakthrough),并给出建议切入
    时间点与关联核心概念。数量按主题动态产出(一般 3-6 个),不再写死为 5。
    """

    hook_id: str = Field(default="", max_length=32)
    title: str = Field(default="", max_length=120)
    narrative_function: HookNarrativeFunction = "opening_suspense"
    suggested_placement_s: float = Field(default=0.0, ge=0.0, le=3_600)
    text: str = Field(min_length=1, max_length=2_000)
    associated_concepts: list[str] = Field(default_factory=list, max_length=16)


class ExplainerCue(BaseModel):
    # LLM-generated drafts commonly provide only an estimated duration.  Keep
    # accepting the older explicit ``time_range`` wire field, but derive a
    # stable placeholder when it is omitted so the draft can reach the review
    # UI and be edited there instead of failing schema validation at E0.
    time_range: Optional[str] = Field(  # noqa: UP045 - explicit API compatibility type
        default=None,
        min_length=3,
        max_length=32,
        description="时间范围，如 00:00-00:05",
    )
    visual_type: VisualType
    text: str = Field(min_length=1, max_length=2_000)
    visual_config: dict[str, Any] = Field(default_factory=dict)
    step_id: int | str | None = None
    # ``None`` was accepted by the previous contract; retain that input
    # compatibility while normalising omitted/null values to the 5s default.
    time_estimate_s: float | None = Field(default=5.0, gt=0, le=300)
    target_url: str | None = None
    highlight_selector: str | None = None
    chart_data: dict[str, Any] | None = None
    code_text: str | None = None
    language: str | None = None

    @model_validator(mode="before")
    @classmethod
    def ensure_time_range(cls, data: Any) -> Any:
        """Derive a reviewable placeholder for model output without a range.

        The placeholder deliberately starts at zero: the final cumulative
        timeline is created by the assembly/ASR stage.  It is only a valid,
        editable cue range for the research response and remains compatible
        with clients that still send an explicit ``MM:SS-MM:SS`` range.
        """
        if not isinstance(data, dict):
            return data
        if data.get("time_range"):
            return data
        values = dict(data)
        estimate = values.get("time_estimate_s")
        if estimate is None:
            estimate = 5.0
            values["time_estimate_s"] = estimate
        values["time_range"] = f"00:00-{float(estimate):04.1f}s"
        return values

    @field_validator("time_range")
    @classmethod
    def validate_time_range(cls, value: str) -> str:
        value = value.strip()
        if "-" not in value:
            raise ValueError("time_range 必须是 MM:SS-MM:SS 或 00:00-05.0s")
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
    # v9: Hook 策略矩阵。数量按知识节点动态产出(一般 3-6),不再写死 5 个。
    # 每个节点携带叙事功能档位与建议切入时间点,供确稿台做链式组合。
    hooks: list[HookNode] = Field(min_length=1, max_length=12)
    # 与 hooks 同构的别名,保留给旧客户端与调试视图。
    hook_details: list[HookNode] = Field(default_factory=list)
    # Script variants are editorial options, not a fixed-size protocol.  Any
    # non-empty list can move into the human review stage.
    scripts: list[ExplainerScriptDraft] = Field(min_length=1)
    script_versions: list[ExplainerScriptDraft] = Field(default_factory=list)
    provider: str
    decision_trail: list[dict[str, Any]] = Field(default_factory=list)


class ExplainerAssembleRequest(BaseModel):
    # The v6 wire contract only requires the approval payload.  The topic is
    # optional because the research session may already be persisted server
    # side; clients that keep it locally can still send it for traceability.
    topic_or_url: str = Field(default="", max_length=20_000)
    voice_profile: str = "cosyvoice_default"
    # ``presenter_id`` is the HEVI-owned reusable preset.  The legacy
    # ``heygen_presenter_id`` remains accepted for older clients and is
    # resolved to a provider ID only at the authenticated API boundary.
    presenter_id: str | None = None
    heygen_presenter_id: str | None = None
    presenter_provider: Literal["remotion", "heygen"] = "remotion"
    presenter_name: str = "HEVI 默认解说数字人"
    # v9: Hook 策略矩阵。selected_hook 兼容旧客户端;selected_hooks 是确稿台
    # 多选后的 Hook 链(按 narrative_function 顺序排序),hook_combination 记录
    # 组合模式(串联贯穿 chain / 融合开场 fusion)。
    selected_hook: str = Field(default="", max_length=500)
    selected_hooks: list[str] = Field(default_factory=list, max_length=12)
    hook_combination: Literal["chain", "fusion"] = "chain"
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
    hooks: list[HookNode]
    scripts: list[ExplainerScriptDraft]
    provider: str
    decision_trail: list[dict[str, Any]] = Field(default_factory=list)
