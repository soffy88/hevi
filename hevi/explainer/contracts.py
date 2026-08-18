"""Explainer Master v8 contracts.

The research and assembly endpoints intentionally use a small, explicit
contract.  The UI can edit the visual scaffold without knowing anything about
the provider implementation, while the task adapter keeps the durable task
and artifact semantics that the rest of HEVI already uses.
"""

from __future__ import annotations

import json
from contextlib import suppress
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

VisualType = Literal[
    "heygen_avatar",
    "broll_news",
    "browser_broll",
    "stock_broll",
    "data_screenshot",
    "remotion_chart",
    "remotion_code",
    "manim_scene",
    "voiceover",
]

AudioStyle = Literal["formal", "conversational"]

LayoutMode = Literal["fullscreen", "broll_pip"]


class ExplainerResearchRequest(BaseModel):
    topic_or_url: str = Field(min_length=1, max_length=20_000)
    voice_profile: str = "cosyvoice_default"
    heygen_presenter_id: str | None = None
    # 断点续传:客户端可携带已有 session_id 覆盖旧缓存;空值由服务端生成。
    session_id: str = Field(default="", max_length=64)
    # 精准目标时长:"1-3"/"3-6"/"6-10"/"10-15" 等范围档,或单个分钟数如 "8"/"20"。
    # LLM 生成时按约 250 字/分钟动态计算总字数底线与视觉 Cue 数量。
    target_duration: str = Field(
        default="1-3",
        description="目标时长，格式为范围(如'1-3')或具体分钟数(如'8')",
    )

    @field_validator("topic_or_url")
    @classmethod
    def topic_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("topic_or_url 不能为空")
        return value

    @field_validator("target_duration")
    @classmethod
    def target_duration_must_be_range_or_number(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("target_duration 不能为空")
        parts = value.split("-")
        try:
            bounds = [float(part) for part in parts]
        except ValueError as exc:
            raise ValueError("target_duration 应为分钟数或 '低-高' 范围") from exc
        if len(bounds) == 1:
            low = high = bounds[0]
        elif len(bounds) == 2:
            low, high = bounds
        else:
            raise ValueError("target_duration 格式无效:最多一个连字符")
        if low <= 0 or high < low or high > 60:
            raise ValueError("target_duration 需满足 0 < 低 <= 高 <= 60(分钟)")
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


class ConceptExpansion(BaseModel):
    """素材吸收与扩写映射表条目 —— 反压缩机制的核心(Chain-of-Thought in Schema)。

    LLM 必须在写任何台词之前,先遍历用户提供的全部素材,把每个硬核知识点拆成
    一条映射:原文素材点 + 深度扩写。deep_explanation 由 LLM 自行挖掘前因后果、
    历史背景、底层原理、数学/物理图景,并用通俗比喻讲透,不得少于 150 字。
    矩阵做到 100% 覆盖,漏掉任何一段素材即视为废稿。
    """

    original_material_point: str = Field(
        min_length=1,
        max_length=2_000,
        description="原文素材中的核心知识点或原句",
    )
    deep_explanation: str = Field(
        min_length=50,
        max_length=6_000,
        description=(
            "把该知识点彻底讲透的深度扩写(至少 150 字):前因后果、历史背景、"
            "底层原理、技术/数学/物理图景 + 通俗比喻,禁止一句话带过。"
        ),
    )
    source: str = Field(
        default="", max_length=500, description="素材出处(无法核验可为空)"
    )


class ScriptVersionMeta(BaseModel):
    """分章生成模式下,单个脚本版本的元信息(Step A 产出,不含 cues)。"""

    id: str = ""
    title: str
    viewpoint: str = ""
    hook: str = ""
    # 思考链:本版如何把核心理论讲透(展开哪些反常点/用什么数据/从哪个原理切入/怎么收束)。
    reasoning_depth: str = Field(default="", max_length=4_000)


class VideoPackaging(BaseModel):
    """🚨 v9.0: 视频包装配置 —— 强制的独立节点,不可与 cues 混在一起。
    
    LLM 必须显式指定开场主题画参数,Remotion 在 Frame 0 渲染 3-5s 标题卡序列。
    """

    main_title: str = Field(
        min_length=2,
        max_length=120,
        description="视频主题大标题，将显示在开场 3 秒封面上",
    )
    subtitle: str = Field(
        default="",
        max_length=200,
        description="副标题或核心信息点",
    )
    theme_image_query: str = Field(
        default="",
        description="用于搜索开场背景图的高精度英文关键词 (如 'Cyberpunk server rack dark')",
    )
    presenter_image_url: str = Field(
        default="",
        description=(
            "数字人母体照片 URL（可选）。可上传或选择一张带背景的高清照片"
            "作为全时段解说员。"
        ),
    )

    @field_validator("main_title")
    @classmethod
    def main_title_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("main_title 不能为空，这是视频的命脉！")
        return value


class ChapterPlan(BaseModel):
    """超长视频的分章大纲:每章携带与本章主题相关的素材吸收与扩写条目。

    章节的 expansions 是全局 material_coverage_matrix 的子集(非空),
    逐章生成台词时整组喂给 LLM,保证该章素材 100% 被吸收。
    """

    chapter_id: str = Field(default="", max_length=32)
    title: str = Field(min_length=1, max_length=120)
    goal: str = Field(
        min_length=20,
        max_length=2_000,
        description="本章要讲透什么:从哪个反常点切入、用什么数据/图表/比喻支撑、收束到什么结论",
    )
    expansions: list[ConceptExpansion] = Field(min_length=1, max_length=30)


class ExplainerOutline(BaseModel):
    """分章生成 Step A 的产出:研究 + 素材吸收矩阵 + 分章大纲 + 版本元信息。

    故意不含 cues —— 台词在 Step B 逐章生成,避免单次超长 JSON 的 Attention
    衰减与损坏,同时强制 LLM 先完成深度扩写再动笔。
    """

    research_summary: str = ""
    facts: list[ResearchFact] = Field(default_factory=list)
    hooks: list[HookNode] = Field(default_factory=list, max_length=12)
    # 全局素材吸收与扩写矩阵:100% 覆盖选题全部硬核知识节点。
    material_coverage_matrix: list[ConceptExpansion] = Field(default_factory=list)
    # 4-5 章是理想产出;本地模型截断/少产出时,≥2 章也值得抢救(台词照常逐章生成)。
    chapters: list[ChapterPlan] = Field(min_length=2, max_length=6)
    versions: list[ScriptVersionMeta] = Field(min_length=1, max_length=5)


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
    visual_type: VisualType = "voiceover"
    audio_style: AudioStyle = "formal"
    text: str = Field(
        min_length=1,
        max_length=2_000,
        description=(
            "解说旁白文本。核心段落必须详实深入，字数建议在 100-200 字以上，切忌假大空和过度精简。"
        ),
    )
    visual_config: dict[str, Any] = Field(default_factory=dict)
    step_id: int | str | None = None
    # ``None`` was accepted by the previous contract; retain that input
    # compatibility while normalising omitted/null values to the 5s default.
    time_estimate_s: float | None = Field(
        default=5.0,
        gt=0,
        le=300,
        description="预估时长(秒)。核心解说段落应当在 30 秒到 60 秒之间。",
    )
    target_url: str | None = Field(
        default=None,
        description=(
            "如果 visual_type 是 browser_broll，必须提供真实的维基百科、"
            "官方数据页面URL，绝不能捏造！"
        ),
    )
    highlight_selector: str | None = None
    chart_data: dict[str, Any] | None = None
    code_text: str | None = None
    language: str | None = None
    # 🚨 v9.0: 视觉搜索查询 —— stock_broll 专用。LLM 输出 3-5 个精准英文关键词供后端检索真实素材。
    visual_search_query: str = Field(
        default="",
        description=(
            "仅当 visual_type==stock_broll 时必填：3-5 个极高精度的英文搜索关键词"
            "（逗号分隔），用于 Pexels/Unsplash API 检索匹配画面。"
        ),
    )
    # 🚨 v9.0: 布局模式控制 —— 驱动 Remotion 全屏/PiP 切换
    layout_mode: LayoutMode = "fullscreen"

    @model_validator(mode="before")
    @classmethod
    def ensure_time_range(cls, data: Any) -> Any:
        """Derive a reviewable placeholder for model output without a range.

        The placeholder deliberately starts at zero: the final cumulative
        timeline is created by the assembly/ASR stage.  It is only a valid,
        editable cue range for the research response and remains compatible
        with clients that still send an explicit ``MM:SS-MM:SS`` range.

        隐患点 B 防爆:整个 cue 被序列化成 JSON 字符串时先解包,绝不把 .get()
        打在 str 上(『str』 object has no attribute 'get' 从根上灭绝)。
        """
        if isinstance(data, str):
            # json.loads 失败(纯文本等)直接放弃解包,交给下方 isinstance 守卫。
            with suppress(Exception):
                data = json.loads(data)
        if not isinstance(data, dict):
            return data  # 放弃 get 操作,让 Pydantic 报原本的 validation error
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
    # 思考链:LLM 在写台词前先说明本版脚本如何把核心理论讲透(展开哪些反常点、
    # 用什么数据支撑、从哪个原理切入、怎么收束),强制先想清楚再写,提升篇幅与深度。
    reasoning_depth: str = Field(default="", max_length=4_000)
    # 🚨 v9.0: 强制视频包装节点 —— 开场主题画配置，Remotion 必须在 Frame 0 渲染
    # v9.1 查漏补缺:research.py 尚未在 LLM 输出中生成该字段,缺省时给安全兜底
    # (main_title 非空校验仍生效——一旦 LLM 真正产出 packaging 就按校验执行)。
    packaging: VideoPackaging = Field(
        default_factory=lambda: VideoPackaging(main_title="HEVI 深度解说"),
        description=(
            "🚨 强制！视频的开场主题画与数字人母体配置。含 main_title/"
            "subtitle/theme_image_query/presenter_image_url。"
        ),
    )
    # 🚨 素材吸收与扩写映射表:强制 LLM 在写台词前先遍历全部素材并做深度扩写,
    # 100% 覆盖用户提供的所有素材点,不得遗漏任何一段(反压缩机制核心)。
    material_coverage_matrix: list[ConceptExpansion] = Field(
        default_factory=list,
        description=(
            "必须 100% 覆盖用户提供的所有素材点,并在 deep_explanation 中进行"
            "硬核扩写(≥150 字),绝不允许漏掉任何一段素材!"
        ),
    )
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
    # 素材吸收与扩写映射表(跨脚本版本并集):确稿台可在选定版本前直接查看
    # 全部素材点被如何深度扩写,反压缩质量可视化。
    material_coverage_matrix: list[ConceptExpansion] = Field(default_factory=list)
    # 断点续传:本次调研的缓存 key,刷新页面后凭它从缓存恢复确稿台状态。
    session_id: str = Field(default="", max_length=64)


# 研究任务状态(与 research_cache.ResearchStatus 同步)。
ResearchStatus = Literal["pending", "processing", "ready", "failed"]


class ExplainerResearchJob(BaseModel):
    """异步研究任务的状态信封 —— 根治长视频研究的 524 超时。

    POST /research 不再同步跑完再回(分章生成长视频动辄几百秒,Cloudflare
    100s 就 524);改成立刻派研究后台任务并落盘一个 processing 信封,
    HTTP 连接秒回 202。前端轮询 GET /research/{session_id} 拿到信封:
    - processing:继续轮询(可显示进度文案)
    - ready:payload 即完整 ExplainerResearchResponse,进入确稿台
    - failed:显示 error,提供重试入口
    原断点续传语义保留:ready 状态的信封 payload 就是完整的阶段一数据。
    """

    session_id: str = Field(max_length=64)
    status: ResearchStatus
    topic_or_url: str = Field(default="", max_length=20_000)
    error: str | None = None
    payload: ExplainerResearchResponse | None = None


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
    # 断点续传:关联到 research 阶段的缓存会话(仅记录,不参与装配)。
    session_id: str = Field(default="", max_length=64)
    enable_remotion_code_render: bool = True
    enable_manim_render: bool = True
    enable_circle_avatar_mask: bool = True
    enable_browser_broll: bool = True
    aspect_ratio: Literal["9:16", "16:9"] = "9:16"
    # v9.1: 数字人母体照片 URL(全时段 Talking Face 底轨素材),经 asset_validator 质检。
    presenter_image_url: str = Field(default="", max_length=2048)
    presenter_reference_video: str = Field(default="", max_length=2048)
    # 60–90 秒试播闸:先 preview_mode,确认后再 preview_confirmed 渲全片。
    preview_mode: bool = False
    preview_confirmed: bool = False


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
    # 素材吸收与扩写映射表(跨脚本版本并集,去重)。
    material_coverage_matrix: list[ConceptExpansion] = Field(default_factory=list)
